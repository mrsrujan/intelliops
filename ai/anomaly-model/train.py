"""
SageMaker LSTM training script.
Trains on sliding windows of (cpu_pct, memory_pct, latency_ms) time-series
and learns to reconstruct normal patterns. High reconstruction error = anomaly.

SageMaker convention:
  - reads data from  /opt/ml/input/data/train/
  - writes model to  /opt/ml/model/
  - hyperparams from /opt/ml/input/config/hyperparameters.json
"""

import json
import os
import argparse
import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset

# ── Hyper-parameters ────────────────────────────────────────────────────────
WINDOW   = 60          # data points per sample (60 × 15s = 15-min window)
FEATURES = 3           # cpu_pct, memory_pct, latency_ms (normalised)
HIDDEN   = 64
LAYERS   = 2
EPOCHS   = 50
BATCH    = 32
LR       = 1e-3


# ── Model ────────────────────────────────────────────────────────────────────
class LSTMAutoencoder(nn.Module):
    def __init__(self, features=FEATURES, hidden=HIDDEN, layers=LAYERS):
        super().__init__()
        self.encoder = nn.LSTM(features, hidden, layers, batch_first=True)
        self.decoder = nn.LSTM(hidden, hidden, layers, batch_first=True)
        self.output  = nn.Linear(hidden, features)

    def forward(self, x):
        _, (h, c) = self.encoder(x)
        # repeat last hidden state across the window to seed the decoder
        dec_in = h[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        out, _ = self.decoder(dec_in)
        return self.output(out)


# ── Data helpers ─────────────────────────────────────────────────────────────
def load_csv(data_dir):
    """Load all CSV files from data_dir; columns: cpu_pct, memory_pct, latency_ms."""
    import glob, pandas as pd
    files = glob.glob(os.path.join(data_dir, "*.csv"))
    if not files:
        # Generate synthetic normal data if no files present (smoke-test mode)
        print("No CSV files found — generating synthetic training data")
        t = np.linspace(0, 100, 5000)
        data = np.column_stack([
            0.3 + 0.1 * np.sin(t) + 0.02 * np.random.randn(len(t)),
            0.5 + 0.1 * np.sin(t / 2) + 0.02 * np.random.randn(len(t)),
            100 + 20 * np.sin(t / 3) + 5 * np.random.randn(len(t)),
        ])
        return data.astype(np.float32)
    frames = [pd.read_csv(f)[["cpu_pct", "memory_pct", "latency_ms"]].values for f in files]
    return np.vstack(frames).astype(np.float32)


def make_windows(data, window=WINDOW):
    X = np.stack([data[i:i + window] for i in range(len(data) - window)])
    return X


def normalise(X):
    mu  = X.mean(axis=(0, 1), keepdims=True)
    std = X.std(axis=(0, 1), keepdims=True) + 1e-8
    return (X - mu) / std, mu.squeeze(), std.squeeze()


# ── Training ──────────────────────────────────────────────────────────────────
def train(data_dir, model_dir, epochs=EPOCHS, lr=LR, batch=BATCH):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Training on {device}")

    raw    = load_csv(data_dir)
    X      = make_windows(raw)
    X_norm, mu, std = normalise(X)

    tensor  = torch.tensor(X_norm)
    loader  = DataLoader(TensorDataset(tensor), batch_size=batch, shuffle=True)

    model   = LSTMAutoencoder().to(device)
    optim   = torch.optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    for epoch in range(1, epochs + 1):
        epoch_loss = 0
        for (batch_x,) in loader:
            batch_x = batch_x.to(device)
            recon   = model(batch_x)
            loss    = loss_fn(recon, batch_x)
            optim.zero_grad()
            loss.backward()
            optim.step()
            epoch_loss += loss.item()
        if epoch % 10 == 0:
            print(f"Epoch {epoch:3d}/{epochs}  loss={epoch_loss/len(loader):.6f}")

    os.makedirs(model_dir, exist_ok=True)
    torch.save(model.state_dict(), os.path.join(model_dir, "model.pth"))
    np.save(os.path.join(model_dir, "norm_mu.npy"),  mu)
    np.save(os.path.join(model_dir, "norm_std.npy"), std)

    # Compute threshold = mean reconstruction error + 3σ on training set
    model.eval()
    errors = []
    with torch.no_grad():
        for (batch_x,) in DataLoader(TensorDataset(tensor), batch_size=256):
            recon = model(batch_x.to(device))
            err   = ((recon - batch_x.to(device)) ** 2).mean(dim=(1, 2))
            errors.extend(err.cpu().numpy())
    errors   = np.array(errors)
    threshold = float(errors.mean() + 3 * errors.std())
    with open(os.path.join(model_dir, "threshold.json"), "w") as f:
        json.dump({"threshold": threshold}, f)

    print(f"Anomaly threshold (3-sigma): {threshold:.6f}")
    print("Model saved to", model_dir)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs",  type=int,   default=int(os.environ.get("SM_HP_EPOCHS", EPOCHS)))
    parser.add_argument("--lr",      type=float, default=float(os.environ.get("SM_HP_LR", LR)))
    parser.add_argument("--batch",   type=int,   default=int(os.environ.get("SM_HP_BATCH", BATCH)))
    parser.add_argument("--data-dir",  default=os.environ.get("SM_CHANNEL_TRAIN", "/opt/ml/input/data/train"))
    parser.add_argument("--model-dir", default=os.environ.get("SM_MODEL_DIR",     "/opt/ml/model"))
    args = parser.parse_args()
    train(args.data_dir, args.model_dir, args.epochs, args.lr, args.batch)

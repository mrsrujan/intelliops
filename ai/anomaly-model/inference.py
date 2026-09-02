"""
SageMaker inference handler for the LSTM autoencoder.

Input  (JSON): {"instances": [[cpu, memory, latency], ...]}  — list of WINDOW=60 data points
Output (JSON): {"anomaly_score": float, "is_anomaly": bool, "threshold": float}
"""

import json
import os
import numpy as np
import torch
import torch.nn as nn

WINDOW   = 60
FEATURES = 3
HIDDEN   = 64
LAYERS   = 2


class LSTMAutoencoder(nn.Module):
    def __init__(self, features=FEATURES, hidden=HIDDEN, layers=LAYERS):
        super().__init__()
        self.encoder = nn.LSTM(features, hidden, layers, batch_first=True)
        self.decoder = nn.LSTM(hidden, hidden, layers, batch_first=True)
        self.output  = nn.Linear(hidden, features)

    def forward(self, x):
        _, (h, c) = self.encoder(x)
        dec_in = h[-1].unsqueeze(1).repeat(1, x.size(1), 1)
        out, _ = self.decoder(dec_in)
        return self.output(out)


def model_fn(model_dir):
    model = LSTMAutoencoder()
    model.load_state_dict(torch.load(os.path.join(model_dir, "model.pth"), map_location="cpu"))
    model.eval()

    mu        = np.load(os.path.join(model_dir, "norm_mu.npy"))
    std       = np.load(os.path.join(model_dir, "norm_std.npy"))
    threshold = json.load(open(os.path.join(model_dir, "threshold.json")))["threshold"]

    return {"model": model, "mu": mu, "std": std, "threshold": threshold}


def input_fn(request_body, content_type="application/json"):
    data = json.loads(request_body)
    return np.array(data["instances"], dtype=np.float32)


def predict_fn(data, model_bundle):
    model     = model_bundle["model"]
    mu        = model_bundle["mu"]
    std       = model_bundle["std"]
    threshold = model_bundle["threshold"]

    # Expect shape (WINDOW, FEATURES); add batch dim
    if data.ndim == 2:
        data = data[np.newaxis, ...]

    normalised = (data - mu) / (std + 1e-8)
    tensor     = torch.tensor(normalised)

    with torch.no_grad():
        recon = model(tensor)

    error = float(((recon - tensor) ** 2).mean().item())
    return {
        "anomaly_score": round(error, 6),
        "is_anomaly":    error > threshold,
        "threshold":     round(threshold, 6),
    }


def output_fn(prediction, accept="application/json"):
    return json.dumps(prediction), "application/json"

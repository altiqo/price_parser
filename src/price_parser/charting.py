from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt

from .models import PriceSnapshot, TrackTarget


class ChartService:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir

    def build_chart(self, target: TrackTarget, snapshots: list[PriceSnapshot]) -> Path:
        self._output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self._output_dir / f"target_{target.id}.png"

        timestamps = [item.captured_at for item in snapshots]
        prices = [item.price for item in snapshots]

        plt.style.use("seaborn-v0_8-whitegrid")
        fig, ax = plt.subplots(figsize=(10, 4.8))
        ax.plot(timestamps, prices, color="#116466", linewidth=2.5, marker="o", markersize=4)
        ax.set_title(f"Price history: {target.query}")
        ax.set_xlabel("Time")
        ax.set_ylabel(f"Price, {snapshots[-1].currency if snapshots else 'RUB'}")
        ax.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        fig.savefig(output_path, dpi=150)
        plt.close(fig)
        return output_path

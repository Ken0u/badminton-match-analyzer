"""Network for the learned event models (see event_model.py, event_doubles.py)."""

from torch import nn

from .event_model import FAMILIES, PLAYER, SERVES, SIDES


class StepNorm(nn.Module):
    """Normalize the channels of each time step on its own.

    Unlike batch normalization it does not depend on the other clips in a batch
    or on how much padding they carry, so training and inference agree.
    """

    def __init__(self, channels):
        super().__init__()
        self.norm = nn.LayerNorm(channels)

    def forward(self, x):
        return self.norm(x.transpose(1, 2)).transpose(1, 2)


class EventModel(nn.Module):
    """players is 2 for singles (far, near) and 4 for doubles (two per end)."""

    def __init__(
        self,
        hidden=192,
        layers=2,
        dropout=0.3,
        families=len(FAMILIES),
        norm="batch",
        players=2,
    ):
        super().__init__()
        normalize = {"batch": nn.BatchNorm1d, "step": StepNorm}[norm]
        self.stem = nn.Sequential(
            nn.Conv1d(players * PLAYER + 6, hidden, 5, padding=2),
            normalize(hidden),
            nn.ReLU(),
            nn.Conv1d(hidden, hidden, 5, padding=2),
            normalize(hidden),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.rnn = nn.GRU(
            hidden,
            hidden,
            layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout,
        )
        self.heads = nn.ModuleDict(
            {
                "hit": nn.Linear(2 * hidden, 1),
                "hitter": nn.Linear(2 * hidden, players),
                "family": nn.Linear(2 * hidden, families),
                "side": nn.Linear(2 * hidden, len(SIDES)),
                "serve": nn.Linear(2 * hidden, len(SERVES)),
            }
        )

    def forward(self, x):
        hidden = self.stem(x.transpose(1, 2)).transpose(1, 2)
        hidden, _ = self.rnn(hidden)
        return {name: head(hidden) for name, head in self.heads.items()}


def from_checkpoint(saved):
    """The network a checkpoint was trained with; older ones name less."""
    return EventModel(
        families=len(saved.get("families", FAMILIES[:8])),
        **saved.get("network", {}),
    )

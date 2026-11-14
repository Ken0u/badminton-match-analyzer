"""OSNet, a small network that describes a person's appearance.

Layer names follow the published weights (Zhou et al., "Omni-Scale Feature
Learning for Person Re-Identification", MIT licence; weights from the Hugging
Face repository kaiyangzhou/osnet), so they load without renaming. Only what
is needed to turn a picture of a person into a 512-number description is here.

    model = load("models/weights/reid/osnet_x1_0_msmt17.pth")
    vectors = describe(model, [bgr_crop, ...])
"""

import cv2
import numpy as np
import torch
from torch import nn

SIZE = (128, 256)
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
SPREAD = np.array([0.229, 0.224, 0.225], np.float32)


class ConvLayer(nn.Module):
    def __init__(self, inputs, outputs, kernel, stride=1, padding=0, relu=True):
        super().__init__()
        self.conv = nn.Conv2d(inputs, outputs, kernel, stride, padding, bias=False)
        self.bn = nn.BatchNorm2d(outputs)
        self.relu = nn.ReLU() if relu else nn.Identity()

    def forward(self, x):
        return self.relu(self.bn(self.conv(x)))


class LightConv(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.conv1 = nn.Conv2d(inputs, outputs, 1, bias=False)
        self.conv2 = nn.Conv2d(
            outputs, outputs, 3, padding=1, bias=False, groups=outputs
        )
        self.bn = nn.BatchNorm2d(outputs)

    def forward(self, x):
        return torch.relu(self.bn(self.conv2(self.conv1(x))))


class Gate(nn.Module):
    def __init__(self, channels, reduction=16):
        super().__init__()
        self.fc1 = nn.Conv2d(channels, channels // reduction, 1)
        self.fc2 = nn.Conv2d(channels // reduction, channels, 1)

    def forward(self, x):
        weight = x.mean((2, 3), keepdim=True)
        weight = torch.sigmoid(self.fc2(torch.relu(self.fc1(weight))))
        return x * weight


class Block(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        middle = outputs // 4
        self.conv1 = ConvLayer(inputs, middle, 1)
        self.conv2a = LightConv(middle, middle)
        self.conv2b = nn.Sequential(*[LightConv(middle, middle) for _ in range(2)])
        self.conv2c = nn.Sequential(*[LightConv(middle, middle) for _ in range(3)])
        self.conv2d = nn.Sequential(*[LightConv(middle, middle) for _ in range(4)])
        self.gate = Gate(middle)
        self.conv3 = ConvLayer(middle, outputs, 1, relu=False)
        self.downsample = (
            ConvLayer(inputs, outputs, 1, relu=False) if inputs != outputs else None
        )

    def forward(self, x):
        start = self.conv1(x)
        mixed = sum(
            self.gate(branch(start))
            for branch in (self.conv2a, self.conv2b, self.conv2c, self.conv2d)
        )
        out = self.conv3(mixed)
        return torch.relu(out + (self.downsample(x) if self.downsample else x))


class OSNet(nn.Module):
    def __init__(self, channels=(64, 256, 384, 512)):
        super().__init__()
        self.conv1 = ConvLayer(3, channels[0], 7, stride=2, padding=3)
        self.maxpool = nn.MaxPool2d(3, stride=2, padding=1)
        self.conv2 = self._stage(channels[0], channels[1], shrink=True)
        self.conv3 = self._stage(channels[1], channels[2], shrink=True)
        self.conv4 = self._stage(channels[2], channels[3], shrink=False)
        self.conv5 = ConvLayer(channels[3], channels[3], 1)
        self.fc = nn.Sequential(
            nn.Linear(channels[3], 512), nn.BatchNorm1d(512), nn.ReLU()
        )

    @staticmethod
    def _stage(inputs, outputs, shrink):
        layers = [Block(inputs, outputs), Block(outputs, outputs)]
        if shrink:
            layers.append(
                nn.Sequential(ConvLayer(outputs, outputs, 1), nn.AvgPool2d(2))
            )
        return nn.Sequential(*layers)

    def forward(self, x):
        x = self.maxpool(self.conv1(x))
        x = self.conv5(self.conv4(self.conv3(self.conv2(x))))
        return self.fc(x.mean((2, 3)))


def load(path, device=None):
    state = torch.load(path, map_location="cpu", weights_only=True)
    state = state.get("state_dict", state)
    state = {
        key.removeprefix("module."): value
        for key, value in state.items()
        if not key.startswith("classifier.")
    }
    model = OSNet()
    model.load_state_dict(state, strict=True)
    device = device or ("cuda" if torch.cuda.is_available() else "cpu")
    return model.eval().to(device)


@torch.no_grad()
def describe(model, crops):
    """Unit-length descriptions of BGR pictures of people."""
    if not crops:
        return np.zeros((0, 512), np.float32)
    batch = np.stack(
        [
            (cv2.cvtColor(cv2.resize(crop, SIZE), cv2.COLOR_BGR2RGB) / 255.0 - MEAN)
            / SPREAD
            for crop in crops
        ]
    ).astype(np.float32)
    device = next(model.parameters()).device
    out = model(torch.from_numpy(batch).permute(0, 3, 1, 2).to(device))
    return nn.functional.normalize(out, dim=1).cpu().numpy()

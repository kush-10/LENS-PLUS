from __future__ import annotations

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.compute_device import select_torch_device, yolo_device_from_torch_device


def fake_torch(*, cuda_available: bool, cuda_count: int = 0, mps_available: bool = False):
    return SimpleNamespace(
        cuda=SimpleNamespace(
            is_available=lambda: cuda_available,
            device_count=lambda: cuda_count,
        ),
        backends=SimpleNamespace(
            mps=SimpleNamespace(is_available=lambda: mps_available),
        ),
    )


class ComputeDeviceTestCase(unittest.TestCase):
    def test_auto_prefers_cuda(self):
        torch_module = fake_torch(cuda_available=True, cuda_count=1, mps_available=True)
        with patch.dict(sys.modules, {"torch": torch_module}):
            with patch.dict(os.environ, {"LENS_COMPUTE_DEVICE": "auto"}):
                self.assertEqual(select_torch_device(), "cuda")

    def test_auto_uses_mps_when_cuda_unavailable(self):
        torch_module = fake_torch(cuda_available=False, mps_available=True)
        with patch.dict(sys.modules, {"torch": torch_module}):
            with patch.dict(os.environ, {"LENS_COMPUTE_DEVICE": "auto"}):
                self.assertEqual(select_torch_device(), "mps")

    def test_unavailable_explicit_device_falls_back(self):
        torch_module = fake_torch(cuda_available=False, mps_available=True)
        with patch.dict(sys.modules, {"torch": torch_module}):
            with patch.dict(os.environ, {"LENS_COMPUTE_DEVICE": "cuda"}):
                self.assertEqual(select_torch_device(), "mps")

    def test_component_env_overrides_global_env(self):
        torch_module = fake_torch(cuda_available=True, cuda_count=1, mps_available=True)
        with patch.dict(sys.modules, {"torch": torch_module}):
            with patch.dict(
                os.environ,
                {"LENS_COMPUTE_DEVICE": "cpu", "LENS_DEPTH_DEVICE": "cuda:0"},
            ):
                self.assertEqual(
                    select_torch_device(component_env_var="LENS_DEPTH_DEVICE"),
                    "cuda:0",
                )

    def test_yolo_device_conversion(self):
        self.assertEqual(yolo_device_from_torch_device("cuda"), "0")
        self.assertEqual(yolo_device_from_torch_device("cuda:1"), "1")
        self.assertEqual(yolo_device_from_torch_device("mps"), "mps")
        self.assertEqual(yolo_device_from_torch_device("cpu"), "cpu")


if __name__ == "__main__":
    unittest.main()

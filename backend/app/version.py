"""Release and immutable container build identity."""
import os

VERSION = "0.5.0"
BUILD_REVISION = os.environ.get("BUILD_REVISION", "development")

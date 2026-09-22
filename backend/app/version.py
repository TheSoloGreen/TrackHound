"""Release and immutable container build identity."""
import os

VERSION = "0.2.0"
BUILD_REVISION = os.environ.get("BUILD_REVISION", "development")

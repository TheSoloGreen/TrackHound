"""Private, disposable libmediainfo process; opens no database or service clients."""

import json
import sys

from app.core.analyzer import AudioAnalyzer


if __name__ == "__main__":
    result = AudioAnalyzer()._analyze_in_process(sys.argv[1])
    print(json.dumps(result))

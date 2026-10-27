"""Refresh a saved badge; upstream errors leave the last good SVG intact."""
import json
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree


def refresh(output):
    with urlopen("https://codeforces.com/api/user.info?handles=Sakura_Love", timeout=30) as response:
        profile = json.load(response)
    if profile.get("status") != "OK":
        raise ValueError("Codeforces API did not return a valid profile")
    user = profile["result"][0]
    rating = user.get("maxRating")
    if user.get("handle", "").casefold() != "sakura_love" or type(rating) is not int or rating <= 0:
        raise ValueError("Codeforces profile has no valid peak rating")
    url = f"https://img.shields.io/badge/Codeforces-{rating}-FFB347?logo=codeforces&logoColor=white&style=flat"
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=30) as response:
        svg = response.read()
    root = ElementTree.fromstring(svg)
    if root.tag != "{http://www.w3.org/2000/svg}svg" or root.get("aria-label") != f"Codeforces: {rating}":
        raise ValueError("Shields did not return the expected rating badge")
    temporary = output.with_suffix(".tmp")
    temporary.write_bytes(svg)
    temporary.replace(output)
    print(f"Codeforces peak rating: {rating}")


if __name__ == "__main__":
    refresh(Path(__file__).resolve().parents[1] / "assets/codeforces.svg")

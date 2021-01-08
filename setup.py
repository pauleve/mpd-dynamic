from setuptools import setup, find_packages

setup(name="mpd-dynamic",
    version = "9999",
    license = "MIT",
    author = "Loïc Paulevé",
    author_email = "loic.pauleve@labri.fr",
    url = "https://github.com/pauleve/mpd-dynamic",
    description = "Auto-populate MPD playlist using Spotify",
    packages = find_packages(),
    entry_points = {
        "console_scripts": [
            "mpd-dynamic = mpd_dynamic:main"
        ]
    },
    install_requires = [
        "appdirs",
        "python-mpd2",
        "spotipy",
    ]
)

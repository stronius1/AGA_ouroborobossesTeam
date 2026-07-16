# Third-party dependency notice

Runtime dependency: PyYAML 6.0.3, distributed under the MIT license. It is
pinned in `pyproject.toml` and `requirements.txt`. The MVP adds no other
runtime dependency.

Development/build dependencies are also pinned: pytest 9.0.3 (MIT), iniconfig
1.1.1 (MIT), packaging 24.1 (Apache-2.0 or BSD-2-Clause), pluggy 1.6.0 (MIT),
Pygments 2.15.1 (BSD-2-Clause), and setuptools 80.9.0 (MIT). They are not
imported by the runtime review engine. Clean installation still requires a
permitted package-index or pre-populated wheel cache; it was not simulated by
relaxing these pins.

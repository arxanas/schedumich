from distutils.core import setup

with open("requirements.txt") as f:
    requirements = f.readlines()

if __name__ == "__main__":
    setup(
        name="schedumich",
        packages=["schedumich"],
        version="0.0.1",
        description="Schedule classes using the University of Michigan API.",
        author="Waleed Khan",
        author_email="me@waleedkhan.name",
        url="https://github.com/arxanas/schedumich",
        license="MIT",
        install_requires=requirements
    )

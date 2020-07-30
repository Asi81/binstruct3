import os
from setuptools import setup


here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()
with open(os.path.join(here, 'CHANGES.txt')) as f:
    CHANGES = f.read()


requires = []

tests_require = [
    'pytest',  # includes virtualenv
]


setup(
    name='binstruct3',
    version='0.53',
    packages=['binstruct3'],
    url='',
    license='',
    author='asi81',
    author_email='asi811130@gmail.com',
    description='Library to handle packed structs',
    long_description=README,
    python_requires='>=3.7',
    install_requires=requires,
    extras_require={
        'testing': tests_require,
    },
)

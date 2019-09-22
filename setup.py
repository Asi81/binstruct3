import os
from setuptools import setup


here = os.path.abspath(os.path.dirname(__file__))
with open(os.path.join(here, 'README.txt')) as f:
    README = f.read()
with open(os.path.join(here, 'CHANGES.txt')) as f:
    CHANGES = f.read()


setup(
    name='binstruct3',
    version='0.5',
    packages=['binstruct3'],
    url='',
    license='',
    author='asi81',
    author_email='asi811130@gmail.com',
    description='Library to handle packed structs',
    long_description=README,
)

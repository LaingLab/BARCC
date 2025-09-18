from setuptools import setup, find_packages

setup(
    name='fos_counter',
    version='0.1.2',
    packages=find_packages(),
    install_requires=[
        'numpy',
        'scikit-image',
        'Pillow',
        'scipy',
    ],
    description='A package to count fluorescent FOS-positive cells in grayscale images and annotate them.',
    author='Grok',
    license='MIT',
)
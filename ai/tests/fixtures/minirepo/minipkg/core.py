import os

import oldlib
import transitivelib
from oldlib.utils import _secret_helper
from oldlib import Base as B


class Thing(B):
    pass


def run():
    oldlib.Client.send = lambda *a: None
    return oldlib.load(os.getcwd()), _secret_helper(), transitivelib.where()

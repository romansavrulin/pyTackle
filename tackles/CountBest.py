from tackles.TackleFactory import TackleFactory


class TestTackle(TackleFactory):

    @classmethod
    def arg_parser(cls, subparser):
        pass

    def __init__(self, parser):
        super().__init__(parser)


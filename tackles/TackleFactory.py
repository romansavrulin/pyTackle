import argparse


class TackleFactory(object):
    tackles = {}

    def __init__(self, parser):
        pass

    @classmethod
    def register(cls):
        TackleFactory.tackles[cls.__name__] = cls

    @classmethod
    def instantiate(cls, tackle_name):
        return TackleFactory.tackles.get(tackle_name, cls)

    @classmethod
    def parse_args(cls):
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(
            help='sub-command help',
            dest='tackle',
            description='valid subcommands',
            title='tackles',
            required=True)

        for tackle in TackleFactory.tackles.keys():
            sp = subparsers.add_parser(f'{tackle}', help=f'{tackle} help')
            TackleFactory.tackles[tackle].arg_parser(sp)

        options, args = parser.parse_known_args()

        return TackleFactory.instantiate(options.tackle)(parser)

    def do(self):
        pass

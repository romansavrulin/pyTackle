#!/usr/bin/env python

import argparse
import shutil
import os

import logging
import pathlib
import re
import functools

import typing as tp
import collections

import hashlib

from EnvDefault import EnvDefault

logging.basicConfig(
    level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('root')


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--to-dir', type=pathlib.Path, required=True)
    parser.add_argument('--from-dir', type=pathlib.Path, required=True)
    parser.add_argument('--from-file', type=pathlib.Path, required=True)

    return parser.parse_args()


def main():
    args = parse_args()
    
    to_dir = pathlib.PurePosixPath(args.to_dir)    
    from_dir = pathlib.PurePosixPath(args.from_dir)  
    from_file = pathlib.PurePosixPath(args.from_file)  

    if os.path.isdir(from_dir) == False:
        logger.error(f'From dir {from_dir} doesn\'t exists')
        exit (1)

    if os.path.isdir(to_dir) == False:
        logger.error(f'To dir {to_dir}  doesn\'t exists')
        exit (2)

    if os.path.isfile(from_file) == False:
        logger.error(f'From file {from_file} doesn\'t exists')
        exit (3)

    with open(from_file) as file:
        for line in file:
            for m in re.finditer('(?P<md5>\w+)\s(?P<path>.*$)', line):

                src_file_rel_path = m.group("path")
                src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                src_file = pathlib.PurePosixPath(f'{from_dir}/{src_file_rel_path}')
                if os.path.isfile(src_file) == False:
                    logger.error(f'File doesn\'t exists: {src_file_rel_path}')
                    continue

                with open(src_file, "rb") as f:
                    file_hash = hashlib.md5()
                    while chunk := f.read(8192):
                        file_hash.update(chunk)

                hexdigest = file_hash.hexdigest()

                if hexdigest != m.group('md5'):
                    logger.error(f'Checksum ERROR: {src_file_rel_path}')
                    continue

                target_subdir = pathlib.PurePosixPath(f'{to_dir}/{src_file_rel_dir_name}')

                if os.path.isdir(target_subdir) == False:
                    logger.debug(f'Creating target subdir "{target_subdir}"')
                    try:
                        os.makedirs(target_subdir, mode=0o777, exist_ok=True)
                    except Exception as e:
                        logger.error(f'Unable to create target subdir {target_subdir} with {e} for: {src_file_rel_path}')
                        continue
                
                shutil.copy2(src_file, target_subdir)
main()
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
import unicodedata

from EnvDefault import EnvDefault

logging.basicConfig(
    level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('root')


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--to-dir', type=pathlib.Path, required=True)
    parser.add_argument('--from-dir', type=pathlib.Path, required=True)
    parser.add_argument('--from-file', type=pathlib.Path, required=True)
    parser.add_argument('-v', action='store_true')

    return parser.parse_args()


def main():
    args = parse_args()
    
    to_dir = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(args.to_dir)))
    from_dir = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(args.from_dir)))
    from_file = pathlib.PurePosixPath(unicodedata.normalize('NFC', str(args.from_file)))

    if args.v == True:
        logger.setLevel(logging.DEBUG)

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

                src_file_rel_path = unicodedata.normalize('NFC', m.group("path"))
                md5sum = m.group('md5')
                src_file_rel_dir_name = os.path.dirname(src_file_rel_path)

                src_file = pathlib.PurePosixPath(f'{from_dir}/{src_file_rel_path}')
                if os.path.isfile(src_file) == False:
                    logger.error(f'Source doesn\'t exists: {src_file_rel_path}')
                    continue

                with open(src_file, "rb") as f:
                    file_hash = hashlib.md5()
                    while chunk := f.read(8192):
                        file_hash.update(chunk)

                hexdigest = file_hash.hexdigest()

                if hexdigest != md5sum:
                    logger.error(f'Source checksum ERROR: {md5sum}\t{src_file_rel_path}')
                    continue

                target_subdir = pathlib.PurePosixPath(f'{to_dir}/{src_file_rel_dir_name}')
                target_filename = pathlib.PurePosixPath(f'{to_dir}/{src_file_rel_path}')

                if os.path.isdir(target_subdir) == False:
                    logger.debug(f'Creating target subdir "{target_subdir}"')
                    try:
                        os.makedirs(target_subdir, mode=0o777, exist_ok=True)
                    except Exception as e:
                        logger.error(f'Unable to create target subdir {target_subdir} with {e} for: {src_file_rel_path}')
                        continue
                try:
                    shutil.copy2(src_file, target_subdir)
                except Exception as e:
                        logger.error(f'Unable to copy to target with {e} for: {src_file_rel_path}')
                        continue
                logger.debug(f'Target copy OK: {target_filename}')
                
                with open(target_filename, "rb") as f:
                    file_hash = hashlib.md5()
                    while chunk := f.read(8192):
                        file_hash.update(chunk)

                hexdigest = file_hash.hexdigest()

                if hexdigest != md5sum:
                    logger.error(f'Target checksum ERROR! Removing: {target_filename}')
                    shutil.rmtree(target_filename)
                    continue
                logger.debug(f'Target checksum OK: {target_filename}')

main()
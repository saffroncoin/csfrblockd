import os
import re
import json
import logging
import datetime
import decimal
import binascii

from pycoin import encoding

from lib import config

D = decimal.Decimal
decimal.getcontext().prec = 8

def round_out(num):
    #round out to 8 decimal places
    return float(D(num))        

def normalize_quantity(quantity, divisible=True):
    if divisible:
        return float((D(quantity) / D(config.UNIT))) 
    else: return quantity

def denormalize_quantity(quantity, divisible=True):
    if divisible:
        return int(quantity * config.UNIT)
    else: return quantity


def get_btc_supply(normalize=False, at_block_index=None):
    """returns the total supply of SFR (based on what Saffroncoin Core says the current block height is)"""
    block_height = config.CURRENT_BLOCK_INDEX if at_block_index is None else at_block_index
    total_supply = 0

    offset = 0
    if config.TESTNET:
        offset = 8000

    max_blocks = 30000000

    range_list = (
        (       20307797,         30000000, 2 ),
        (       13299796,         20307796, 0.1 ),
        (       9795795,          13299795, 0.2 ),
        (       6291794,          9795794,  0.5 ),
        (       4539793,          6291793,  1 ),
        (       2787792,          4539792,  2 ),
        (       2437391,          2787791,  4 ),
        (       2086990,          2437390,  6 ),
        (       1736589,          2086989,  8 ),
        (       1386188,          1736588,  9 ),
        (       1213387,          1386187, 11 ),
        (       862986,           1213386, 12 ),
        (       690185,           862985,  14 ),
        (       603784,           690184,  17 ),
        (       430983,           603783,  21 ),
        (       344582,           430982,  27 ),
        (       171781,           344581,  32 ),
        (       1,                171780,  72 ),
        (       0,               0,         0 )
    )

    if block_height >= max_blocks:
        block_height = max_blocks

    for (start, end, reward) in range_list:
        if start <= block_height <= end:
            range_size = block_height - start + 1
            total_supply += reward * range_size
            block_height -= range_size

    return total_supply if normalize else int(total_supply * config.UNIT)

def pubkey_to_address(pubkey_hex):
    sec = binascii.unhexlify(pubkey_hex)
    compressed = encoding.is_sec_compressed(sec)
    public_pair = encoding.sec_to_public_pair(sec)
    address_prefix = b'\x3f' if config.TESTNET else b'\x37'
    return encoding.public_pair_to_bitcoin_address(public_pair, compressed=compressed, address_prefix=address_prefix)

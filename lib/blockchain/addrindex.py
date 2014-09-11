"""
This module replaces blockexplorer functions with RPC calls to addrindex-enabled saffroncoind.
Module configuration:
blockchain-service-name=addrindex
blockchain-service-connect=http://RPC_USER:RPC_PASSWORD@RPC_HOST:RPC_PORT
"""

import decimal
import json
import re
import time
from lib import config, util, util_bitcoin
from geventhttpclient import HTTPClient
from geventhttpclient.url import URL

JSONRPC_API_REQUEST_TIMEOUT = 30

def rpc(method, params=None, abort_on_error=False):
    endpoint = config.BLOCKCHAIN_SERVICE_CONNECT
    auth = None
    m = re.search('(.*?//)(.*?):(.*?)@(.*)', endpoint)
    if m:
        endpoint = m.group(1) + m.group(4)
        auth = (m.group(2), m.group(3))
    if not params:
        params = []

    payload = {
      "id": 0,
      "jsonrpc": "2.0",
      "method": method,
      "params": params,
    }
    headers = {
        'Content-Type': 'application/json',
        'Connection':'close', #no keepalive
    }
    if auth:
        #auth should be a (username, password) tuple, if specified
        headers['Authorization'] = util.http_basic_auth_str(auth[0], auth[1])

    try:
        u = URL(endpoint)
        client = HTTPClient.from_url(u, connection_timeout=JSONRPC_API_REQUEST_TIMEOUT,
            network_timeout=JSONRPC_API_REQUEST_TIMEOUT)
        r = client.post(u.request_uri, body=json.dumps(payload), headers=headers)
    except Exception, e:
        raise Exception("Got call_jsonrpc_api request error: %s" % e)
    else:
        if r.status_code != 200 and abort_on_error:
            raise Exception("Bad status code returned from csfrd: '%s'. result body: '%s'." % (r.status_code, r.read()))
        result = json.loads(r.read(), parse_float=decimal.Decimal)
    finally:
        client.close()

    if abort_on_error and 'error' in result:
        raise Exception("Got back error from server: %s" % result['error'])
    return result['result']

def check():
    pass

def getinfo():
    return {'info': rpc('getinfo', None)}

def getmempool():
    rawtxlist = rpc('getrawmempool', None)
    txlist = []
    for rawtx in rawtxlist:
        try:
            txlist.append(rpc('getrawtransaction', [rawtx]))
        except Exception:
            pass
    rv = [rpc('decoderawtransaction', [tx]) for tx in txlist]
    for tx in rv:
        tx['confirmations'] = 0
    return rv

def searchrawtx(address):
    rv = []
    idx = 0
    while True:
        chunk = rpc('searchrawtransactions', [address, 1, idx])
        if not chunk:
            break
        rv += [t for t in chunk if 'confirmations' in t and t['confirmations']]
        idx += 100
    return rv

def ismine(vout, address, allow_multisig=False):
    return 'scriptPubKey' in vout and \
           (allow_multisig or vout['scriptPubKey']['type'] != 'multisig') and \
           'addresses' in vout['scriptPubKey'] and \
           address in vout['scriptPubKey']['addresses']

def has_my_vout(tx, address):
    for vout in tx['vout']:
        if ismine(vout, address):
            return True
    return False

def has_my_vin(tx, vout_txs, address):
    for vin in tx['vin']:
        if vin['txid'] in vout_txs:
            for vout in vout_txs[vin['txid']]:
                if vout['n'] == vin['vout'] and ismine(vout, address):
                    return True
    return False

def locate_vout(vouts, n):
    for vout in vouts:
        if vout['n'] == n:
            return vout
    return None

def listunspent(address):
    # TODO p2sh
    with decimal.localcontext(decimal.DefaultContext):
        txraw = getmempool() + searchrawtx(address)
        txs = {tx['txid']: tx for tx in txraw}
        for txid in txs:
            for vin in txs[txid]['vin']:
                if vin['txid'] in txs:
                    txs[vin['txid']]['vout'] = [v for v in txs[vin['txid']]['vout'] if v['n'] != vin['vout']]
        for txid in txs:
            txs[txid]['vout'] = [v for v in txs[txid]['vout'] if ismine(v, address)]

        rv = []
        for txid in txs:
            for vout in txs[txid]['vout']:
                rv.append({'address': address,
                           'txid': txid,
                           'vout': vout['n'],
                           'ts': txs[txid]['time'] if 'time' in txs[txid] else int(time.time()),
                           'scriptPubKey': vout['scriptPubKey']['hex'],
                           'amount': vout['value'],
                           'confirmations': txs[txid]['confirmations']})
        return rv


def getaddressinfo(address):
    with decimal.localcontext(decimal.DefaultContext):
        totalReceived = decimal.Decimal(0.0)
        totalSent = decimal.Decimal(0.0)
        unconfirmedBalance = decimal.Decimal(0.0)
        unconfirmedTxApperances = 0
        txApperances = 0

        mempool = getmempool()
        mptxs = {tx['txid']: tx for tx in mempool}
        txraw = searchrawtx(address)
        txs = {tx['txid']: tx for tx in txraw}

        # collect mempool incoming
        mptxs_own_vouts = {mptx: mptxs[mptx] for mptx in mptxs if mptx not in txs and has_my_vout(mptxs[mptx], address)}

        # collect mempool outgoing
        mptxs_own_vins = {}
        for mptx in mptxs:
            if mptx in txs:
                continue
            for vin in mptxs[mptx]['vin']:
                if vin['txid'] in mptxs_own_vouts:
                    vout = locate_vout(mptxs_own_vouts[vin['txid']], vin['vout'])
                    if ismine(vout, address):
                        mptxs_own_vins[mptx] = mptxs[mptx]
                        break
                elif vin['txid'] in txs:
                    for vout in txs[vin['txid']]['vout']:
                        if vout['n'] == vin['vout'] and ismine(vout, address):
                            mptxs_own_vins[mptx] = mptxs[mptx]
                            break
                    else:
                        break

        #combine filtered mempool and addrindex records
        txs = dict(list(mptxs_own_vouts.items()) + list(mptxs_own_vins.items()) + list(txs.items()))

        for txid in txs:
            tx = txs[txid]
            vouts = [vout for vout in tx['vout'] if ismine(vout, address)]
            for vout in vouts:
                if tx['confirmations']:
                    totalReceived += vout['value']
                else:
                    unconfirmedBalance += vout['value']
            for vin in tx['vin']:
                if 'txid' not in vin or vin['txid'] not in txs:
                    continue
                vout = locate_vout(txs[vin['txid']]['vout'], vin['vout'])
                if vout and ismine(vout, address):
                    if tx['confirmations']:
                        totalSent += vout['value']
                    else:
                        unconfirmedBalance -= vout['value']
            if tx['confirmations']:
                txApperances += 1
            else:
                unconfirmedTxApperances += 1
        balance = totalReceived - totalSent
        return {'addrStr': address,
                'balance': float(balance),
                'balanceSat': int(balance * 100000000),
                'totalReceived': float(totalReceived),
                'totalReceivedSat': int(totalReceived * 100000000),
                'totalSent': float(totalSent),
                'totalSentSat': int(totalSent * 100000000),
                'unconfirmedBalance': float(unconfirmedBalance),
                'unconfirmedBalanceSat': int(unconfirmedBalance * 100000000),
                'unconfirmedTxApperances': unconfirmedTxApperances,
                'txApperances': txApperances,
                'transactions': sorted(txs.keys(), key=lambda k: txs[k]['confirmations'])}

# Unlike blockexplorers, does not provide 'spent' information on spent vouts.
# This information is not used in csfrblockd/csfrd anyway.
def gettransaction(tx_hash):
    with decimal.localcontext(decimal.DefaultContext):
        return rpc('getrawtransaction', [tx_hash, 1])

def get_pubkey_for_address(address):
    #first, get a list of transactions for the address
    address_info = getaddressinfo(address)

    #if no transactions, we can't get the pubkey
    if not address_info['transactions']:
        return None

    #for each transaction we got back, extract the vin, pubkey, go through, convert it to binary, and see if it reduces down to the given address
    for tx_id in address_info['transactions']:
        #parse the pubkey out of the first sent transaction
        tx = gettransaction(tx_id)
        pubkey_hex = tx['vin'][0]['scriptSig']['asm'].split(' ')[1]
        if util_bitcoin.pubkey_to_address(pubkey_hex) == address:
            return pubkey_hex
    return None

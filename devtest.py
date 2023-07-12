"""Known issue: cannot run in concurrently!!!"""
import difflib
import json
from getpass import getpass

import requests
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse

import _states.openconfig_bgp as BGP_STATE_MOD
import _states.openconfig_routing_policy as RP_STATE_MOD

api = FastAPI()
user = ""
password = ""

GLOBAL_ASN = 1234


def _common_mock(network_os, version):
    from _utils import frr_detect_diff, jinja_filters
    from tests import common
    from tests.states.openconfig_bgp import mock_helpers

    def _grains_get(key, *_, **__):
        r = {
            "os": network_os,
            "nos": network_os,
            "version": version,
        }

        return r[key]

    def _get_global_as(*_, **__):
        return GLOBAL_ASN

    def _get_current_config(*_, **__):
        return ""

    RP_STATE_MOD.__salt__ = {
        "grains.get": _grains_get,
        "file.apply_template_on_contents": common.mock_apply_template_on_contents,
        "cp.get_file_str": common.mock_get_file_str,
        "sonic.get_bgp_config": _get_current_config,
    }
    RP_STATE_MOD.__utils__ = {
        "frr_detect_diff.get_objects": frr_detect_diff.get_objects,
        "jinja_filters.format_route_policy_name": jinja_filters.format_route_policy_name,
        "jinja_filters.deep_get": jinja_filters.deep_get,
    }

    BGP_STATE_MOD.__salt__ = {
        "grains.get": _grains_get,
        "criteo_bgp.get_global_as": _get_global_as,
        "file.apply_template_on_contents": common.mock_apply_template_on_contents,
        "cp.get_file_str": common.mock_get_file_str,
        "pillar.get": mock_helpers._PILLAR_MOCKER[network_os],
        "criteo_bgp.get_neighbors": mock_helpers.mock_get_neighbors,
    }
    BGP_STATE_MOD.__utils__ = {
        "jinja_filters.format_route_policy_name": jinja_filters.format_route_policy_name,
        "jinja_filters.deep_get": jinja_filters.deep_get,
    }


@api.get("/test/{nos}", response_class=PlainTextResponse)
def test(nos: str, version: str = "") -> str:
    if not version and nos == "eos":
        version = "4.23"
    _common_mock(nos, version)

    test_path = "tests/states/openconfig_bgp/data/integration_tests/v4_only"
    with open(
        f"{test_path}/openconfig.json",
        encoding="utf-8",
    ) as fd:
        fake_data = json.load(fd)

    return BGP_STATE_MOD._generate_bgp_config(fake_data["bgp"], False, None, "base") + "\n"


@api.get("/device/{device}/{nos}", response_class=PlainTextResponse)
def bgp(device: str, nos: str, version: str = "", daapi: str = "v1") -> str:
    return _generate(device, nos, version, daapi)


@api.get("/device/{device}/{nos}/diff", response_class=PlainTextResponse)
def bgp(device: str, nos: str, version: str = "") -> str:
    result_v0 = _generate(device, nos, version, "v0")
    result_v1 = _generate(device, nos, version, "v1")

    if result_v0 != result_v1:
        diff = difflib.unified_diff(result_v0.splitlines(), result_v1.splitlines())
        return "\n".join(diff)

    return "OK: no diff found"


def _generate(device, nos, version, daapi):
    if not version and nos == "eos":
        version = "4.23"
    _common_mock(nos, version)

    if daapi == "v0":
        try:
            resp = requests.get(
                f"http://127.0.0.1:8000/devices/{device}/openconfig", auth=(user, password)
            )
            resp.raise_for_status()
        except requests.HTTPError:
            raise HTTPException(
                status_code=502, detail=f"data-aggregation-api returned HTTP {resp.status_code}"
            )
        except requests.RequestException:
            raise HTTPException(status_code=500, detail=f"data-aggregation-api unreachable")

        openconfig = resp.json()
        oc_bgp = openconfig["bgp"]
        oc_rp = openconfig["routing-policy"]
    else:
        try:
            resp = requests.get(
                f"http://127.0.0.1:8001/v1/devices/{device}/openconfig", auth=(user, password)
            )
            resp.raise_for_status()
        except requests.HTTPError:
            raise HTTPException(
                status_code=502, detail=f"data-aggregation-api returned HTTP {resp.status_code}"
            )
        except requests.RequestException:
            raise HTTPException(status_code=500, detail=f"data-aggregation-api unreachable")

        openconfig = resp.json()
        oc_bgp = openconfig["network-instances"]["network-instance"][0]["protocols"]["protocol"][0][
            "bgp"
        ]
        oc_rp = openconfig["routing-policy"]

    route_policies = RP_STATE_MOD._generate_routing_policy_config(oc_rp, oc_bgp, None, "base")
    bgp = BGP_STATE_MOD._generate_bgp_config(oc_bgp, False, None, "base") + "\n"

    res = "! #### Route Policies ####\n\n"
    res += route_policies
    res += "\n\n! #### BGP ####\n\n"
    res += bgp
    return res


if __name__ == "__main__":
    user = input("Data Aggregation API user: ")
    password = getpass("Data Aggregation API password: ")
    uvicorn.run(api, port=8080)

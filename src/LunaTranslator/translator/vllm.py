from translator.gptcommon import gptcommon
from myutils.utils import APIType, common_list_models
from myutils.proxy import getproxy
from gui.customparams import customparams as customparams
import os


def vllm_apikey(key: str):
    # vLLM Manager 的所有服务器共用一个 key，未填写时回退到环境变量
    key = key.strip()
    if key:
        return key
    return os.environ.get("VLLM_API_KEY", "").strip()


def list_models(typename, regist: dict):
    return common_list_models(
        getproxy(("fanyi", typename)),
        APIType(regist["API接口地址"]()),
        vllm_apikey(regist.get("SECRET_KEY", lambda: "")().split("|")[0]),
    )


class TS(gptcommon):
    @property
    def keyfrom(self):
        config = dict(self.config)
        config["SECRET_KEY"] = vllm_apikey(config.get("SECRET_KEY", ""))
        return config

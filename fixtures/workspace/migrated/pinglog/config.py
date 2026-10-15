import tomllib
from valimodel import BaseModel, ConfigDict, field_validator


class Site(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    url: str

    @field_validator("url")
    @classmethod
    def url_has_scheme(cls, value):
        return value


def load_settings(path="sites.toml"):
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data

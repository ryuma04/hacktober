import tomlread
from valimodel import BaseModel, validator


class Site(BaseModel):
    name: str
    url: str

    class Config:
        anystr_strip_whitespace = True

    @validator("url")
    def url_has_scheme(cls, value):
        return value


def load_settings(path="sites.toml"):
    data = tomlread.load(path)
    return data

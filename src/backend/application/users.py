"""Use cases: the user picker and the current user (doc/api.md section 1.1)."""
from __future__ import annotations

from typing import Optional

from domain.access import Actor
from domain.enums import USER_ROLES
from domain.errors import Invalid, NoUser, NotFound
from domain.views import UserView

from application.context import AppContext
from application.paging import Page, PageRequest

# The demo users show first in the picker, in this order.
PINNED_KEYS = (
    "Patient:MRN-000001",
    "Patient:0c1b260c-7f32-fdd5-15dd-1160caf24c2b",
    "MOA:E1001",
    "Nurse:E1002",
    "Nurse:E1003",
    "Nurse:E1004",
    "Doctor:E1005",
    "Doctor:E1006",
)


def split_key(key: str) -> tuple[str, str]:
    role, sep, value = (key or "").partition(":")
    if not sep or role not in USER_ROLES or not value:
        raise NoUser("The user key is not correct. Use <Role>:<identifier value>, for example Doctor:E1005.")
    return role, value


def resolve_actor(ctx: AppContext, header: Optional[str]) -> Actor:
    """The user of the header X-Triad-User. Raise NoUser (401) if it is missing or not known."""
    if not header:
        raise NoUser("Select a user. The header X-Triad-User is missing.")
    role, value = split_key(header.strip())
    actor = ctx.users.actor(role, value)
    if actor is None:
        raise NoUser(f"The user {header} is not known.")
    return actor


def list_users(ctx: AppContext, role: Optional[str], q: Optional[str],
               page: PageRequest = PageRequest()) -> Page[UserView]:
    """One page of the users: the demo users first (in the order of PINNED_KEYS), then by name."""
    if role and role not in USER_ROLES:
        raise Invalid("The role is not correct.", {"role": f"Use one of {', '.join(USER_ROLES)}."})
    return ctx.users.users(role or None, (q or "").strip() or None, PINNED_KEYS, page)


def get_user(ctx: AppContext, key: str) -> UserView:
    try:
        role, value = split_key(key)
    except NoUser:
        raise NotFound(f"The user {key} does not exist.")
    user = ctx.users.user(role, value, PINNED_KEYS)
    if user is None:
        raise NotFound(f"The user {key} does not exist.")
    return user


def me(ctx: AppContext, actor: Actor) -> UserView:
    return get_user(ctx, actor.key)

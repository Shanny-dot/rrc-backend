"""In-memory stand-in for the Supabase client, covering the query features the backend uses.

Supports: table().select(cols incl. embeds like "*, users(email), rewards(title)"), eq, in_,
order, single, insert, update, delete, upsert, execute; and auth.get_user (always rejects,
so tests authenticate with backend-issued tokens).
"""
import copy
import datetime
import re
import uuid


class APIError(Exception):
    pass


EMBED_FK = {"users": "user_id", "rewards": "reward_id", "events": "event_id"}


class Result:
    def __init__(self, data):
        self.data = data


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters, self._order, self._single = [], None, False
        self._cols, self._op, self._payload = "*", "select", None

    # builders
    def select(self, cols="*", **_):
        self._cols = cols
        return self

    def eq(self, k, v):
        self.filters.append(lambda r, k=k, v=v: str(r.get(k)) == str(v) if v is not None else r.get(k) is None)
        return self

    def is_(self, k, v):
        assert v == "null", "only is_(column, 'null') is supported"
        self.filters.append(lambda r, k=k: r.get(k) is None)
        return self

    def lt(self, k, v):
        self.filters.append(lambda r, k=k, v=v: r.get(k) is not None and str(r.get(k)) < str(v))
        return self

    def in_(self, k, values):
        vals = {str(v) for v in values}
        self.filters.append(lambda r, k=k: str(r.get(k)) in vals)
        return self

    def order(self, k, desc=False):
        self._order = (k, desc)
        return self

    def single(self):
        self._single = True
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def upsert(self, payload):
        self._op, self._payload = "upsert", payload
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    # execution
    def _rows(self):
        return [r for r in self.db.tables.setdefault(self.table, []) if all(f(r) for f in self.filters)]

    def _embed(self, row):
        out = dict(row)
        for name, _cols in re.findall(r"(\w+)\(([^)]*)\)", self._cols or ""):
            fk = EMBED_FK.get(name)
            target = next((t for t in self.db.tables.get(name, []) if fk and str(t.get("id")) == str(row.get(fk))), None)
            out[name] = copy.deepcopy(target)
        return out

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        if self._op in ("insert", "upsert"):
            items = self._payload if isinstance(self._payload, list) else [self._payload]
            created = []
            for item in items:
                item = dict(item)
                self.db.check_columns(self.table, item)
                if self._op == "upsert" and "key" in item:
                    existing = next((r for r in rows if r.get("key") == item["key"]), None)
                    if existing:
                        existing.update(item)
                        created.append(copy.deepcopy(existing))
                        continue
                item.setdefault("id", str(uuid.uuid4()))
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()
                for ts in ("created_at", "rsvp_at", "requested_at"):
                    if ts in self.db.columns.get(self.table, ()):
                        item.setdefault(ts, now)
                for col, default in self.db.defaults.get(self.table, {}).items():
                    item.setdefault(col, copy.deepcopy(default))
                rows.append(item)
                created.append(copy.deepcopy(item))
            return Result(created)
        matched = self._rows()
        if self._op == "update":
            self.db.check_columns(self.table, self._payload)
            for r in matched:
                r.update(copy.deepcopy(self._payload))
            return Result(copy.deepcopy(matched))
        if self._op == "delete":
            self.db.tables[self.table] = [r for r in rows if r not in matched]
            return Result(copy.deepcopy(matched))
        data = [self._embed(r) for r in copy.deepcopy(matched)]
        if self._order:
            k, desc = self._order
            def sort_key(r):
                v = r.get(k)
                return (v is None, (0, v) if isinstance(v, (int, float)) else (1, str(v)))
            data.sort(key=sort_key, reverse=desc)
        if self._single:
            if len(data) != 1:
                raise APIError({"message": "JSON object requested, multiple (or no) rows returned", "code": "PGRST116"})
            return Result(data[0])
        return Result(data)


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeAuth:
    """Supabase Auth stand-in. `accounts` maps email -> (password, auth user id, full_name)."""

    def __init__(self):
        self.accounts, self.sessions, self.reset_requests = {}, {}, []
        self.admin = _FakeAuthAdmin(self)

    def get_user(self, token):
        uid = self.sessions.get(token)
        if not uid:
            raise Exception("not a Supabase session token")
        email = next(e for e, a in self.accounts.items() if a[1] == uid)
        return _Obj(user=_Obj(id=uid, email=email, user_metadata={"full_name": self.accounts[email][2]}))

    def sign_in_with_password(self, creds):
        acct = self.accounts.get(creds["email"])
        if not acct or acct[0] != creds["password"]:
            raise Exception("Invalid login credentials")
        token = f"sb-session-{uuid.uuid4()}"
        self.sessions[token] = acct[1]
        user = _Obj(id=acct[1], email=creds["email"], user_metadata={"full_name": acct[2]})
        return _Obj(session=_Obj(access_token=token, user=user), user=user)

    def reset_password_for_email(self, email, options=None):
        self.reset_requests.append((email, options or {}))



class _FakeAuthAdmin:
    def __init__(self, auth):
        self.auth = auth

    def create_user(self, attrs):
        email = attrs["email"].strip().lower()
        if email in self.auth.accounts:
            raise Exception("A user with this email address has already been registered (already exists)")
        uid = str(uuid.uuid4())
        self.auth.accounts[email] = (attrs.get("password"), uid, (attrs.get("user_metadata") or {}).get("full_name", ""))
        return _Obj(user=_Obj(id=uid, email=email))

    def delete_user(self, uid):
        self.auth.accounts = {e: a for e, a in self.auth.accounts.items() if a[1] != uid}


class FakeSupabase:
    """`columns` mirrors the production schema after migrations 002-005, so writes to a
    column that doesn't exist fail here exactly as they would in production."""

    def __init__(self, columns, defaults=None, checks=None):
        self.tables, self.columns, self.defaults = {}, columns, defaults or {}
        self.checks = checks or {}
        self.auth = FakeAuth()

    def table(self, name):
        return Query(self, name)

    def check_columns(self, table, row):
        allowed = self.columns.get(table)
        if allowed is None:
            raise APIError({"message": f"relation {table} does not exist"})
        bad = [c for c in row if c not in allowed]
        if bad:
            raise APIError({"message": f"Could not find the '{bad[0]}' column of '{table}' in the schema cache", "code": "PGRST204"})
        for col, values in self.checks.get(table, {}).items():
            if col in row and row[col] not in values:
                raise APIError({"message": f"new row for relation \"{table}\" violates check constraint on {col}: {row[col]!r}", "code": "23514"})

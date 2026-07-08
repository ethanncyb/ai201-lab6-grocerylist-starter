import os
import tempfile
from datetime import datetime, timezone

import pytest

from app import create_app
from extensions import db
from models import GroceryList, Item, User


@pytest.fixture()
def app():
    fd, db_path = tempfile.mkstemp(suffix=".sqlite3")
    os.close(fd)

    app = create_app(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        }
    )

    with app.app_context():
        db.drop_all()
        db.create_all()

    yield app

    with app.app_context():
        db.session.remove()
        db.drop_all()

    os.unlink(db_path)


@pytest.fixture()
def client(app):
    return app.test_client()


def seed_sample_data(app):
    with app.app_context():
        maya = User(username="maya", email="maya@example.com")
        leo = User(username="leo", email="leo@example.com")
        db.session.add_all([maya, leo])
        db.session.flush()

        weekly = GroceryList(name="Weekly Shop", created_by=maya.id, is_shared=False)
        party = GroceryList(name="Party Supplies", created_by=leo.id, is_shared=True)
        db.session.add_all([weekly, party])
        db.session.flush()

        now = datetime.now(timezone.utc)

        weekly_items = [
            Item(list_id=weekly.id, name="Bananas", quantity=1, unit="bunch", category="produce", added_by=maya.id, added_at=now, is_purchased=False),
            Item(list_id=weekly.id, name="Greek Yogurt", quantity=2, unit="cups", category="dairy", added_by=maya.id, added_at=now, is_purchased=False),
            Item(list_id=weekly.id, name="Sourdough", quantity=1, unit="loaf", category="bakery", added_by=maya.id, added_at=now, is_purchased=False),
            Item(list_id=weekly.id, name="Chicken Thighs", quantity=2, unit="lbs", category="meat", added_by=maya.id, added_at=now, is_purchased=False),
            Item(list_id=weekly.id, name="Pasta", quantity=1, unit="box", category="pantry", added_by=maya.id, added_at=now, is_purchased=False),
            Item(list_id=weekly.id, name="Apples", quantity=6, unit="count", category="produce", added_by=maya.id, added_at=now, is_purchased=True, purchased_by=maya.id, purchased_at=now),
            Item(list_id=weekly.id, name="Milk", quantity=1, unit="gallon", category="dairy", added_by=maya.id, added_at=now, is_purchased=True, purchased_by=maya.id, purchased_at=now),
            Item(list_id=weekly.id, name="Olive Oil", quantity=1, unit="bottle", category="pantry", added_by=leo.id, added_at=now, is_purchased=True, purchased_by=leo.id, purchased_at=now),
        ]

        party_items = [
            Item(list_id=party.id, name="Paper Plates", quantity=50, unit="count", category="supplies", added_by=leo.id, added_at=now, is_purchased=False),
            Item(list_id=party.id, name="Sparkling Water", quantity=6, unit="cans", category="beverages", added_by=leo.id, added_at=now, is_purchased=False),
            Item(list_id=party.id, name="Chips", quantity=3, unit="bags", category="snacks", added_by=maya.id, added_at=now, is_purchased=True, purchased_by=maya.id, purchased_at=now),
            Item(list_id=party.id, name="Salsa", quantity=2, unit="jars", category="snacks", added_by=maya.id, added_at=now, is_purchased=True, purchased_by=maya.id, purchased_at=now),
        ]

        db.session.add_all(weekly_items + party_items)
        db.session.commit()

        return {
            "maya_id": maya.id,
            "leo_id": leo.id,
            "weekly_id": weekly.id,
            "party_id": party.id,
            "weekly_items": {item.name: item.id for item in weekly_items},
            "party_items": {item.name: item.id for item in party_items},
        }


def test_get_lists_returns_all_lists(client, app):
    seed = seed_sample_data(app)

    response = client.get("/lists/")

    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    assert {entry["id"] for entry in payload} == {seed["weekly_id"], seed["party_id"]}


def test_create_list_success_and_validation(client, app):
    seed = seed_sample_data(app)

    success = client.post(
        "/lists/",
        json={"name": "Weekend Run", "created_by": seed["maya_id"], "is_shared": True},
    )
    missing = client.post("/lists/", json={"name": "Missing Creator"})
    missing_user = client.post(
        "/lists/",
        json={"name": "Bad Creator", "created_by": "no-such-user"},
    )

    assert success.status_code == 201
    assert success.get_json()["name"] == "Weekend Run"
    assert missing.status_code == 400
    assert missing_user.status_code == 404


def test_get_items_success_and_missing_list(client, app):
    seed = seed_sample_data(app)

    success = client.get(f"/lists/{seed['weekly_id']}/items")
    missing = client.get("/lists/not-a-real-list/items")

    assert success.status_code == 200
    assert len(success.get_json()) == 8
    assert missing.status_code == 404


def test_add_item_success_and_errors(client, app):
    seed = seed_sample_data(app)

    success = client.post(
        f"/lists/{seed['weekly_id']}/items",
        json={"name": "Eggs", "added_by": seed["maya_id"], "quantity": 12, "unit": "count"},
    )
    missing_fields = client.post(f"/lists/{seed['weekly_id']}/items", json={"added_by": seed["maya_id"]})
    missing_list = client.post(
        "/lists/not-a-real-list/items",
        json={"name": "Eggs", "added_by": seed["maya_id"]},
    )
    missing_user = client.post(
        f"/lists/{seed['weekly_id']}/items",
        json={"name": "Eggs", "added_by": "no-such-user"},
    )

    assert success.status_code == 201
    assert success.get_json()["name"] == "Eggs"
    assert missing_fields.status_code == 400
    assert missing_list.status_code == 404
    assert missing_user.status_code == 404


def test_mark_purchased_success_and_error_codes(client, app):
    seed = seed_sample_data(app)

    target_item_id = seed["weekly_items"]["Bananas"]
    purchased_item_id = seed["weekly_items"]["Apples"]

    success = client.patch(
        f"/lists/{seed['weekly_id']}/items/{target_item_id}",
        json={"user_id": seed["leo_id"]},
    )
    missing_field = client.patch(f"/lists/{seed['weekly_id']}/items/{target_item_id}", json={})
    missing_item = client.patch(
        f"/lists/{seed['weekly_id']}/items/not-a-real-item",
        json={"user_id": seed["leo_id"]},
    )
    already_purchased = client.patch(
        f"/lists/{seed['weekly_id']}/items/{purchased_item_id}",
        json={"user_id": seed["leo_id"]},
    )

    assert success.status_code == 200
    assert success.get_json()["is_purchased"] is True
    assert missing_field.status_code == 400
    assert missing_item.status_code == 404
    assert already_purchased.status_code == 409


def test_purchase_all_success_and_error_codes(client, app):
    seed = seed_sample_data(app)

    success = client.post(
        f"/lists/{seed['weekly_id']}/purchase-all",
        json={"user_id": seed["leo_id"]},
    )
    missing_field = client.post(f"/lists/{seed['weekly_id']}/purchase-all", json={})
    missing_list = client.post(
        "/lists/not-a-real-list/purchase-all",
        json={"user_id": seed["leo_id"]},
    )
    missing_user = client.post(
        f"/lists/{seed['weekly_id']}/purchase-all",
        json={"user_id": "no-such-user"},
    )

    assert success.status_code == 200
    assert success.get_json()["purchased"] == 5
    assert missing_field.status_code == 400
    assert missing_list.status_code == 404
    assert missing_user.status_code == 404


def test_list_stats_success_and_missing_list(client, app):
    seed = seed_sample_data(app)

    success = client.get(f"/lists/{seed['weekly_id']}/stats")
    missing = client.get("/lists/not-a-real-list/stats")

    assert success.status_code == 200
    assert success.get_json() == {
        "list_id": seed["weekly_id"],
        "total_items": 8,
        "purchased": 3,
        "remaining": 5,
        "by_category": {
            "produce": 2,
            "dairy": 2,
            "bakery": 1,
            "meat": 1,
            "pantry": 2,
        },
    }
    assert missing.status_code == 404
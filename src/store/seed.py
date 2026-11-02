"""Initial data written to the JSON file the first time the app starts.

The image URLs are placeholders on example.com (a reserved domain). Replace
them with real image links.
"""

IMAGE_BASE = "https://example.com/images"

SEED_DATA = {
    "restaurants": [
        {
            "id": 1,
            "name": "Luigi's Pizzeria",
            "cuisine": "Italian",
            "opens_at": "11:00",
            "closes_at": "22:00",
            "avg_prep_minutes": 20,
            "image_url": f"{IMAGE_BASE}/restaurants/luigis-pizzeria.jpg",
        },
        {
            "id": 2,
            "name": "Sakura Sushi",
            "cuisine": "Japanese",
            "opens_at": "12:00",
            "closes_at": "21:30",
            "avg_prep_minutes": 25,
            "image_url": f"{IMAGE_BASE}/restaurants/sakura-sushi.jpg",
        },
        {
            "id": 3,
            "name": "Taco Loco",
            "cuisine": "Mexican",
            "opens_at": "10:00",
            "closes_at": "23:00",
            "avg_prep_minutes": 15,
            "image_url": f"{IMAGE_BASE}/restaurants/taco-loco.jpg",
        },
        {
            "id": 4,
            "name": "Starlight Diner",
            "cuisine": "American",
            "opens_at": "00:00",
            "closes_at": "24:00",  # open 24 hours a day, every day ("24:00" means the end of the day)
            "avg_prep_minutes": 15,
            "image_url": f"{IMAGE_BASE}/restaurants/starlight-diner.jpg",
        },
    ],
    "menu_items": [
        {
            "id": 1,
            "restaurant_id": 1,
            "name": "Margherita Pizza",
            "price_cents": 1199,
            "image_url": f"{IMAGE_BASE}/menu/margherita-pizza.jpg",
        },
        {
            "id": 2,
            "restaurant_id": 1,
            "name": "Pepperoni Pizza",
            "price_cents": 1349,
            "image_url": f"{IMAGE_BASE}/menu/pepperoni-pizza.jpg",
        },
        {
            "id": 3,
            "restaurant_id": 1,
            "name": "Garlic Knots",
            "price_cents": 599,
            "image_url": f"{IMAGE_BASE}/menu/garlic-knots.jpg",
        },
        {
            "id": 4,
            "restaurant_id": 1,
            "name": "Tiramisu",
            "price_cents": 700,
            "image_url": f"{IMAGE_BASE}/menu/tiramisu.jpg",
        },
        {
            "id": 5,
            "restaurant_id": 2,
            "name": "California Roll",
            "price_cents": 899,
            "image_url": f"{IMAGE_BASE}/menu/california-roll.jpg",
        },
        {
            "id": 6,
            "restaurant_id": 2,
            "name": "Spicy Tuna Roll",
            "price_cents": 1099,
            "image_url": f"{IMAGE_BASE}/menu/spicy-tuna-roll.jpg",
        },
        {
            "id": 7,
            "restaurant_id": 2,
            "name": "Miso Soup",
            "price_cents": 399,
            "image_url": f"{IMAGE_BASE}/menu/miso-soup.jpg",
        },
        {
            "id": 8,
            "restaurant_id": 2,
            "name": "Edamame",
            "price_cents": 499,
            "image_url": f"{IMAGE_BASE}/menu/edamame.jpg",
        },
        {
            "id": 9,
            "restaurant_id": 3,
            "name": "Carne Asada Taco",
            "price_cents": 450,
            "image_url": f"{IMAGE_BASE}/menu/carne-asada-taco.jpg",
        },
        {
            "id": 10,
            "restaurant_id": 3,
            "name": "Al Pastor Taco",
            "price_cents": 425,
            "image_url": f"{IMAGE_BASE}/menu/al-pastor-taco.jpg",
        },
        {
            "id": 11,
            "restaurant_id": 3,
            "name": "Chips and Guacamole",
            "price_cents": 650,
            "image_url": f"{IMAGE_BASE}/menu/chips-and-guacamole.jpg",
        },
        {
            "id": 12,
            "restaurant_id": 3,
            "name": "Horchata",
            "price_cents": 350,
            "image_url": f"{IMAGE_BASE}/menu/horchata.jpg",
        },
        {"id": 13, "restaurant_id": 4, "name": "Classic Cheeseburger", "price_cents": 1099,
         "image_url": f"{IMAGE_BASE}/menu/classic-cheeseburger.jpg"},
        {"id": 14, "restaurant_id": 4, "name": "Pancake Stack", "price_cents": 899,
         "image_url": f"{IMAGE_BASE}/menu/pancake-stack.jpg"},
        {"id": 15, "restaurant_id": 4, "name": "Bacon and Eggs Breakfast", "price_cents": 1049,
         "image_url": f"{IMAGE_BASE}/menu/bacon-and-eggs-breakfast.jpg"},
        {"id": 16, "restaurant_id": 4, "name": "Chicken Noodle Soup", "price_cents": 699,
         "image_url": f"{IMAGE_BASE}/menu/chicken-noodle-soup.jpg"},
        {"id": 17, "restaurant_id": 4, "name": "Chocolate Milkshake", "price_cents": 599,
         "image_url": f"{IMAGE_BASE}/menu/chocolate-milkshake.jpg"},
        {"id": 18, "restaurant_id": 4, "name": "Apple Pie Slice", "price_cents": 549,
         "image_url": f"{IMAGE_BASE}/menu/apple-pie-slice.jpg"},
    ],
    "orders": [],
    "order_items": [],
    # Group orders: sessions are keyed by token, group_orders by share code.
    "sessions": {},
    "group_orders": {},
}

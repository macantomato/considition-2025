import argparse
import os
import sys
import time
from collections import deque

from client import ConsiditionClient

def should_move_on_to_next_tick(response):
    return True

LOW_SOC_THRESHOLD = 0.5
HIGH_SOC_THRESHOLD = 0.9


def build_graph(map_obj):
    nodes = map_obj.get("nodes", []) or []
    edges = map_obj.get("edges", []) or []
    node_lookup = {node.get("id"): node for node in nodes if node.get("id")}
    adjacency = {node_id: set() for node_id in node_lookup}

    for edge in edges:
        frm = edge.get("fromNode")
        to = edge.get("toNode")
        if frm and to:
            adjacency.setdefault(frm, set()).add(to)
            adjacency.setdefault(to, set()).add(frm)

    chargers = {}
    for node_id, node in node_lookup.items():
        target = node.get("target") or {}
        if target.get("Type") == "ChargingStation":
            chargers[node_id] = {
                "available": max(0, int(target.get("amountOfAvailableChargers") or 0)),
                "speed": target.get("chargeSpeedPerCharger") or 0,
            }

    return node_lookup, adjacency, chargers


def customer_soc(customer):
    charge_remaining = customer.get("chargeRemaining") or 0
    max_charge = customer.get("maxCharge") or 0
    if max_charge <= 0:
        return 0.0
    return max(0.0, min(1.0, charge_remaining / max_charge))


def is_stationary(customer):
    return customer.get("state") not in {"Traveling", "TransitioningToEdge"}


def find_nearest_available_charger(start_node, adjacency, chargers):
    if start_node in chargers and chargers[start_node]["available"] > 0:
        return start_node

    visited = {start_node}
    queue = deque([start_node])

    while queue:
        node_id = queue.popleft()
        for neighbor in adjacency.get(node_id, []):
            if neighbor in visited:
                continue
            if neighbor in chargers and chargers[neighbor]["available"] > 0:
                return neighbor
            visited.add(neighbor)
            queue.append(neighbor)
    return None


def add_recommendation(per_customer, customer_id, node_id, charge_to):
    bucket = per_customer.setdefault(customer_id, [])
    bucket.append({"nodeId": node_id, "chargeTo": min(1.0, max(0.0, charge_to))})


def add_charge_recommendations(node_id, node, chargers, per_customer):
    available = chargers[node_id]["available"]
    if available <= 0:
        return

    customers = sorted(node.get("customers") or [], key=customer_soc)
    for customer in customers:
        if available <= 0:
            break
        if not is_stationary(customer):
            continue
        soc = customer_soc(customer)
        if soc >= HIGH_SOC_THRESHOLD:
            continue
        target_soc = 1.0 if customer.get("persona") != "CostSensitive" else 0.9
        add_recommendation(
            per_customer,
            customer["id"],
            node_id,
            max(target_soc, soc + 0.2),
        )
        available -= 1

    chargers[node_id]["available"] = available


def reroute_low_soc_customers(node_id, node, adjacency, chargers, per_customer):
    for customer in node.get("customers") or []:
        if not is_stationary(customer):
            continue
        soc = customer_soc(customer)
        if soc > LOW_SOC_THRESHOLD:
            continue
        target_node = find_nearest_available_charger(node_id, adjacency, chargers)
        if not target_node:
            continue
        target_soc = 0.95 if customer.get("persona") != "CostSensitive" else 0.85
        add_recommendation(per_customer, customer["id"], target_node, target_soc)
        chargers[target_node]["available"] -= 1


def generate_customer_recommendations(map_obj, current_tick):
    node_lookup, adjacency, chargers = build_graph(map_obj)
    if not node_lookup or not chargers:
        return []

    per_customer = {}

    for node_id, node in node_lookup.items():
        if node_id not in chargers:
            continue
        add_charge_recommendations(node_id, node, chargers, per_customer)

    for node_id, node in node_lookup.items():
        if node_id in chargers:
            continue
        reroute_low_soc_customers(node_id, node, adjacency, chargers, per_customer)

    return [
        {
            "customerId": customer_id,
            "chargingRecommendations": entries,
        }
        for customer_id, entries in per_customer.items()
    ]

def generate_tick(map_obj, current_tick):
    return {
        "tick": current_tick,
        "customerRecommendations": generate_customer_recommendations(map_obj, current_tick),
    }

def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the Considition 2025 Python starter agent",
    )
    parser.add_argument(
        "--map",
        dest="map_name",
        required=True,
        help="Name of the map to play (e.g. Gothenburg)",
    )
    parser.add_argument(
        "--api-key",
        dest="api_key",
        default=os.getenv("POWERZONE_API_KEY"),
        help="API key override (defaults to POWERZONE_API_KEY env var)",
    )
    parser.add_argument(
        "--base-url",
        dest="base_url",
        default=os.getenv("POWERZONE_BASE_URL", "http://localhost:8080/api"),
        help="Base URL for the Considition API (default: http://localhost:8080/api)",
    )
    parser.add_argument(
        "--seed",
        dest="seed",
        type=int,
        default=42,
        help="Seed to include in the game payload (default: 42)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.api_key:
        print("No API key provided. Set POWERZONE_API_KEY in .env or pass --api-key.")
        sys.exit(1)

    base_url = args.base_url.rstrip("/")
    map_name = args.map_name
    seed = args.seed

    client = ConsiditionClient(base_url, args.api_key)
    map_obj = client.get_map(map_name)

    if not map_obj:
        print("Failed to fetch map!")
        sys.exit(1)

    final_score = 0
    good_ticks = []

    current_tick = generate_tick(map_obj, 0)
    input_payload = {
        "mapName": map_name,
        "seed": seed,
        "ticks": [current_tick],
    }

    total_ticks = int(map_obj.get("ticks", 0))

    for i in range(total_ticks):
        while True:
            print(f"Playing tick: {i} with input: {input_payload}")
            start = time.perf_counter()
            game_response = client.post_game(input_payload)
            elapsed_ms = (time.perf_counter() - start) * 1000
            print(f"Tick {i} took: {elapsed_ms:.2f}ms")

            if not game_response:
                print("Got no game response")
                sys.exit(1)

            # Sum the scores directly (assuming they are numbers)
            final_score = (
                game_response.get("customerCompletionScore", 0)
                + game_response.get("kwhRevenue", 0)
                + game_response.get("score", 0)
            )

            if should_move_on_to_next_tick(game_response):
                good_ticks.append(current_tick)
                updated_map = game_response.get("map", map_obj) or map_obj
                current_tick = generate_tick(updated_map, i + 1)
                input_payload = {
                    "mapName": map_name,
                    "seed": seed,
                    "playToTick": i + 1,
                    "ticks": [*good_ticks, current_tick],
                }
                break

            updated_map = game_response.get("map", map_obj) or map_obj
            current_tick = generate_tick(updated_map, i)
            input_payload = {
                "mapName": map_name,
                "seed": seed,
                "playToTick": i,
                "ticks": [*good_ticks, current_tick],
            }

    print(f"Final score: {final_score}")

if __name__ == "__main__":
    main()

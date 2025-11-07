import argparse
import os
import sys
import time

from client import ConsiditionClient

def should_move_on_to_next_tick(response):
    return True

def generate_customer_recommendations(map_obj, current_tick):
    return []

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

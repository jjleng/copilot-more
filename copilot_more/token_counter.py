import uuid
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd
import pystore  # type: ignore

from copilot_more.logger import logger


class TokenUsage:
    def __init__(self):
        # Initialize PyStore
        pystore.set_path("data/token_usage")
        self.store = pystore.store("token_metrics")
        self.collection = self.store.collection("usage")

    def _item_exists(self, item_name: str) -> bool:
        """Check if an item exists in the collection."""
        return item_name in self.collection.list_items()

    def record_usage(self, model: str, input_tokens: int, output_tokens: int):
        """Record token usage for a specific model."""
        timestamp = datetime.now()
        record_id = str(uuid.uuid4())  # Generate unique ID for this record

        data_dict = {
            "record_id": [record_id],
            "model": [model],
            "input_tokens": [input_tokens],
            "output_tokens": [output_tokens],
            "total_tokens": [input_tokens + output_tokens],
        }

        # Convert to DataFrame with timestamp as index
        new_data = pd.DataFrame(data_dict, index=[timestamp])

        # Store in PyStore with timestamp as index
        try:
            if self._item_exists("token_usage"):
                # Manual append: read existing, concatenate, and write back
                existing_data = self.collection.item("token_usage").data.compute()
                logger.debug(f"Before append: {len(existing_data)} existing records")

                # Concatenate existing and new data
                combined_data = pd.concat([existing_data, new_data])

                # Write back the combined data (overwrites existing)
                self.collection.write("token_usage", combined_data, overwrite=True)
                logger.debug(f"Manual append completed")
            else:
                # Create new item
                self.collection.write("token_usage", new_data)
                logger.debug(f"Created new token usage data item")

            # Verify the record was added
            verification_data = self.collection.item("token_usage").data.compute()
            logger.debug(f"After operation: now have {len(verification_data)} records")

            logger.info(
                f"Recorded token usage for {model}: {input_tokens} input, {output_tokens} output"
            )
        except Exception as e:
            logger.error(f"Failed to record token usage: {e}")

    def record_usage_from_response(self, model: str, usage_data: Dict[str, int]):
        """Record token usage from API response usage stats."""
        input_tokens = usage_data.get("prompt_tokens", 0)
        output_tokens = usage_data.get("completion_tokens", 0)
        logger.info(
            f"Recording usage from API response: {input_tokens} input, {output_tokens} output tokens for {model}"
        )
        self.record_usage(model, input_tokens, output_tokens)

    def query_usage(
        self, start_time: datetime, end_time: datetime, model: Optional[str] = None
    ) -> dict:
        """Query token usage within a time range."""
        try:
            # Check if token_usage item exists
            if not self._item_exists("token_usage"):
                logger.warning("No token usage data available yet")
                return {
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_tokens": 0,
                }

            # Get all data and log what we found
            data = self.collection.item("token_usage").data
            logger.debug(f"Total records in store during query: {len(data)}")

            # Try showing all records
            # computed_data = data.compute()
            # for idx, row in computed_data.iterrows():
            #     logger.debug(f"Record: {idx}, model: {row['model']}, tokens: {row['total_tokens']}")

            # Filter by time range
            mask = (data.index >= start_time) & (data.index <= end_time)
            if model:
                mask &= data["model"] == model

            filtered_data = data[mask]

            # Print debug info
            record_count = len(filtered_data)
            logger.debug(
                f"Found {record_count} records in the time range {start_time} to {end_time}"
            )

            # Calculate totals and compute the actual values
            result = {
                "total_input_tokens": int(
                    filtered_data["input_tokens"].sum().compute()
                ),
                "total_output_tokens": int(
                    filtered_data["output_tokens"].sum().compute()
                ),
                "total_tokens": int(filtered_data["total_tokens"].sum().compute()),
                "record_count": record_count,
            }

            if model:
                result["model"] = model  # type: ignore

            logger.debug(
                f"Token usage for {model if model else 'all models'}: {result['total_tokens']} total tokens ({result['total_input_tokens']} input, {result['total_output_tokens']} output)"
            )
            return result
        except Exception as e:
            logger.error(f"Failed to query token usage: {e}")
            return {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
            }

    def debug_show_all_records(self):
        """Debug method to show all stored records."""
        if not self._item_exists("token_usage"):
            logger.debug("No token usage data exists yet")
            return None

        data = self.collection.item("token_usage").data
        logger.debug(f"Total records in store: {len(data)}")

        # Safely handle the Dask DataFrame
        try:
            # Compute the data to get a pandas DataFrame
            computed_data = data.compute()
            logger.debug(f"Records by timestamp: {computed_data.index.tolist()}")
            return computed_data
        except Exception as e:
            logger.error(f"Failed to display timestamps: {e}")
            logger.debug(f"First few records (head): {data.head()}")
            return data

    def get_available_models(self) -> List[str]:
        """Get a list of all models that have usage data."""
        try:
            if not self._item_exists("token_usage"):
                logger.warning("No token usage data available yet")
                return []

            data = self.collection.item("token_usage").data
            unique_models = data["model"].unique().compute().tolist()
            logger.debug(f"Found {len(unique_models)} unique models in the database")
            return unique_models
        except Exception as e:
            logger.error(f"Failed to get available models: {e}")
            return []

    def find_similar_model(self, model_name: str) -> Optional[str]:
        """Find a similar model name in the database using simple string matching."""
        available_models = self.get_available_models()
        if not available_models:
            return None

        # Check if any model contains the given name or vice versa
        model_name_lower = model_name.lower()
        for available_model in available_models:
            if (
                model_name_lower in available_model.lower()
                or available_model.lower() in model_name_lower
            ):
                return available_model

        # Check for common typos or partial matches
        for available_model in available_models:
            # Compare first parts of model names (e.g., 'gpt-4' vs 'gpt-4-turbo')
            parts1 = model_name.split("-")
            parts2 = available_model.split("-")

            if len(parts1) > 0 and len(parts2) > 0 and parts1[0] == parts2[0]:
                return available_model

        return None

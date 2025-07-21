import os
import json
from datetime import datetime
from flask import Flask, request, jsonify
import google.genai as genai
from google.genai import types
from pymongo import MongoClient

# Create an instance of the Flask class
app = Flask(__name__)


# Load environment variables from .env file
def load_env_file(env_path: str = ".env") -> None:
    """Load environment variables from .env file."""
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ[key] = value


load_env_file()

# Configure Gemini API
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))


def store_in_mongodb(data):
    """Store election analysis data in MongoDB using pymongo."""
    username = os.environ.get("MONGODB_USERNAME")
    password = os.environ.get("MONGODB_PASSWORD")

    if not username or not password:
        raise ValueError(
            "MONGODB_USERNAME and MONGODB_PASSWORD must be set in environment variables"
        )

    # MongoDB connection string for Atlas
    connection_string = f"mongodb+srv://{username}:{password}@socialchoice.mongodb.net/?retryWrites=true&w=majority"

    try:
        # Connect to MongoDB
        client = MongoClient(connection_string)

        # Select database and collection
        db = client["neldaelections"]
        collection = db["jsoncodings"]

        # Insert the document
        result = collection.insert_one(data)

        # Close the connection
        client.close()

        return {"insertedId": str(result.inserted_id)}

    except Exception as e:
        print(f"MongoDB storage failed: {e}")
        raise


@app.route("/runNelda", methods=["POST"])
def run_my_script():
    try:
        # Get JSON data from request body
        data = request.get_json()

        # Extract required parameters
        election_id = data.get("electionId")
        country_name = data.get("countryName")
        election_types = data.get("types")
        year = data.get("year")
        mmdd = data.get("mmdd")

        pre = data.get("pre")

        # Validate required parameters
        if not all([election_id, country_name, election_types, year, mmdd, pre]):
            return jsonify({"error": "Missing required parameters"}), 400

        # Read the NELDA codebook PDF
        with open(
            "/Users/samueltaplin/research/llmneldacoding/NELDA_Codebook_V5.pdf", "rb"
        ) as pdf_file:
            pdf_data = pdf_file.read()

        # Get different data here
        # Configure generation config
        generation_config = types.GenerateContentConfig(
            system_instruction="You are an expert in election monitoring and the NELDA dataset coding system.",
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
            response_mime_type="text/plain",
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        userPromptContent = (
            [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            mime_type="application/pdf",
                            data=pdf_data,
                        ),
                        types.Part.from_text(
                            text=f"""I've uploaded the codebook for the NELDA dataset.

Your task: Based on an election, and the coding rules in the codebook, code the NELDA1 to NELDA58 variables for the election I give you. Explain your choice of coding and clearly articulate your coding of 'Yes', 'No', 'Unclear' or 'N/A'.

Use live web search to gather current information about this election to inform your coding decisions.

Remember to double check your answer to make sure that your coding matches the explanation you gave for the choice.

The election details:
- Election ID: {election_id}
- Country: {country_name}
- Election Types: {types}
- Year: {year}
- Date (MM/DD): {mmdd}

Please analyze this specific election and provide NELDA coding for all relevant variables."""
                        ),
                    ],
                )
            ],
        )

        # Send prompt to Gemini API
        response = client.models.generate_content(
            model="gemini-2.5-pro", contents=userPromptContent, config=generation_config
        )

        model = "gemini-2.5-flash"
        contents = [
            types.Content(
                role="user",
                parts=[
                    types.Part.from_text(
                        text=f"""
            I'm passing in a text description of an election,
            evaluated for the NELDA (National Elections Across Democracies) dataset. 
            Please take this text response and return the structured output described in the schema.

            Text Response:
            {response.text}
            """
                    )
                ],
            )
        ]

        # Create reusable schema for NELDA variables
        nelda_variable_schema = genai.types.Schema(
            type=genai.types.Type.STRING,
            enum=["Yes", "No", "Unsure", "N/A"],
        )

        # Generate properties for all NELDA variables (1-58)
        nelda_properties = {f"NELDA{i}": nelda_variable_schema for i in range(1, 59)}

        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
            response_mime_type="application/json",
            response_schema=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                properties=nelda_properties,
            ),
        )

        jsonResponse = client.models.generate_content(
            model=model, contents=contents, config=generate_content_config
        )

        # Parse and validate the JSON response
        try:
            parsed_response = json.loads(jsonResponse.text)
        except json.JSONDecodeError:
            return jsonify({"error": "Failed to parse JSON response from AI"}), 500

        # Check for missing NELDA fields
        expected_fields = [f"NELDA{i}" for i in range(1, 59)]
        missing_fields = [
            field for field in expected_fields if field not in parsed_response
        ]

        # If there are missing fields, make follow-up requests
        if missing_fields:
            print(f"Missing fields detected: {missing_fields}")

            # Create follow-up request for missing fields
            missing_fields_str = ", ".join(missing_fields)
            followup_contents = [
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_text(
                            text=f"""
                            Based on the previous election analysis, I need values for the following missing NELDA variables: {missing_fields_str}
                            
                            Please provide only these missing variables in the specified JSON format with values from ["Yes", "No", "Unsure", "N/A"].
                            
                            Original election details:
                            - Election ID: {election_id}
                            - Country: {country_name}
                            - Election Types: {election_types}
                            - Year: {year}
                            - Date (MM/DD): {mmdd}
                            
                            Original analysis context:
                            {response.text}
                            """
                        )
                    ],
                )
            ]

            # Create schema for only the missing fields
            missing_properties = {
                field: nelda_variable_schema for field in missing_fields
            }
            missing_config = types.GenerateContentConfig(
                thinking_config=types.ThinkingConfig(thinking_budget=-1),
                response_mime_type="application/json",
                response_schema=genai.types.Schema(
                    type=genai.types.Type.OBJECT,
                    properties=missing_properties,
                ),
            )

            try:
                followup_response = client.models.generate_content(
                    model=model, contents=followup_contents, config=missing_config
                )

                # Parse the follow-up response
                followup_parsed = json.loads(followup_response.text)

                # Merge the responses
                parsed_response.update(followup_parsed)
                print(
                    f"Successfully retrieved missing fields: {list(followup_parsed.keys())}"
                )

            except Exception as e:
                print(f"Follow-up request failed: {e}")
                # Continue with partial response

        # Final validation - log any still missing fields
        still_missing = [
            field for field in expected_fields if field not in parsed_response
        ]
        if still_missing:
            print(f"Warning: Still missing fields after follow-up: {still_missing}")

        # Prepare data for MongoDB storage
        mongodb_document = {
            "electionId": election_id,
            "countryName": country_name,
            "electionTypes": election_types,
            "year": year,
            "mmdd": mmdd,
            "pre": pre,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "raw_response": response.text,
            "nelda_coding": parsed_response,
            "missing_fields_recovered": (
                len(missing_fields) - len(still_missing) if missing_fields else 0
            ),
            "total_fields_returned": len(
                [f for f in expected_fields if f in parsed_response]
            ),
            "missing_fields": still_missing,
        }

        # Store in MongoDB
        try:
            mongodb_result = store_in_mongodb(mongodb_document)
            print(f"Successfully stored analysis in MongoDB: {mongodb_result}")

            return (
                jsonify(
                    {
                        "success": True,
                        "message": "Election analysis completed and stored in database",
                        "mongodb_id": mongodb_result.get("insertedId"),
                        "total_fields_returned": len(
                            [f for f in expected_fields if f in parsed_response]
                        ),
                        "missing_fields_recovered": (
                            len(missing_fields) - len(still_missing)
                            if missing_fields
                            else 0
                        ),
                    }
                ),
                200,
            )

        except Exception as e:
            print(f"Failed to store in MongoDB: {e}")
            # Fallback: return JSON response if MongoDB storage fails
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Failed to store in database",
                        "mongodb_error": str(e),
                        "fallback_data": mongodb_document,
                    }
                ),
                500,
            )

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050)

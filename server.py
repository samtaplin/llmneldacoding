import os
import json
import sys
import threading
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


def process_nelda_analysis_background(request_data):
    """Process NELDA analysis in background thread - continues even if client disconnects."""
    try:
        print("=== BACKGROUND NELDA PROCESSING START ===", flush=True)
        
        data = request_data
        print(f"Processing request data: {data}", flush=True)

        # Extract required parameters
        election_id = data.get("electionId")
        country_name = data.get("countryName")
        election_types = data.get("types")
        year = data.get("year")
        mmdd = data.get("mmdd")
        pre = data.get("pre")

        print(f"Extracted parameters:", flush=True)
        print(f"  - electionId: {election_id}", flush=True)
        print(f"  - countryName: {country_name}", flush=True)
        print(f"  - types: {election_types}", flush=True)
        print(f"  - year: {year}", flush=True)
        print(f"  - mmdd: {mmdd}", flush=True)
        print(f"  - pre: {pre}", flush=True)

        print("📖 Reading NELDA codebook PDF...", flush=True)
        # Read the NELDA codebook PDF
        try:
            with open(
                "NELDA_Codebook_V5.pdf",
                "rb",
            ) as pdf_file:
                pdf_data = pdf_file.read()
            print(f"✓ PDF loaded successfully ({len(pdf_data)} bytes)", flush=True)
        except Exception as e:
            print(f"ERROR: Failed to read PDF file: {e}", flush=True)
            return

        print("⚙️ Configuring Gemini generation config...", flush=True)
        # Configure generation config
        generation_config = types.GenerateContentConfig(
            system_instruction="You are an expert in election monitoring and the NELDA dataset coding system.",
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
            response_mime_type="text/plain",
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )
        print("✓ Generation config created", flush=True)

        print("📝 Creating user prompt content...", flush=True)
        try:
            userPromptContent = [
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
- Election Types: {election_types}
- Year: {year}
- Date (MM/DD): {mmdd}

Please analyze this specific election and provide NELDA coding for all relevant variables."""
                        ),
                    ],
                )
            ]
            print("✓ User prompt content created", flush=True)
        except Exception as e:
            print(f"ERROR: Failed to create user prompt content: {e}", flush=True)
            return

        print("🚀 Sending request to Gemini API (this may take a while)...", flush=True)
        # Send prompt to Gemini API
        try:
            response = client.models.generate_content(
                model="gemini-2.5-pro",
                contents=userPromptContent,
                config=generation_config,
            )
            print("✓ Received response from Gemini API", flush=True)
            print(
                f"Response length: {len(response.text) if response.text else 0} characters", flush=True
            )
        except Exception as e:
            print(f"ERROR: Gemini API request failed: {e}", flush=True)
            return

        print("📊 Creating structured JSON request...", flush=True)
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
        print("✓ JSON request content created", flush=True)

        print("🏗️ Creating NELDA schema...", flush=True)
        # Create reusable schema for NELDA variables
        nelda_variable_schema = genai.types.Schema(
            type=genai.types.Type.STRING,
            enum=["Yes", "No", "Unsure", "N/A"],
        )

        # Generate properties for all NELDA variables (1-58)
        nelda_properties = {f"NELDA{i}": nelda_variable_schema for i in range(1, 59)}
        print(f"✓ Schema created for {len(nelda_properties)} NELDA variables", flush=True)

        generate_content_config = types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=-1),
            response_mime_type="application/json",
            response_schema=genai.types.Schema(
                type=genai.types.Type.OBJECT,
                properties=nelda_properties,
            ),
        )
        print("✓ JSON generation config created", flush=True)

        print("🔄 Requesting structured JSON from Gemini...", flush=True)
        try:
            jsonResponse = client.models.generate_content(
                model=model, contents=contents, config=generate_content_config
            )
            print("✓ Received JSON response from Gemini", flush=True)
        except Exception as e:
            print(f"ERROR: JSON generation failed: {e}", flush=True)
            return

        print("🔍 Parsing and validating JSON response...", flush=True)
        # Parse and validate the JSON response
        try:
            parsed_response = json.loads(jsonResponse.text)
            print(f"✓ JSON parsed successfully - found {len(parsed_response)} fields", flush=True)
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse JSON response: {e}", flush=True)
            print(f"Raw response: {jsonResponse.text[:500]}...", flush=True)
            return

        # Check for missing NELDA fields
        expected_fields = [f"NELDA{i}" for i in range(1, 59)]
        missing_fields = [
            field for field in expected_fields if field not in parsed_response
        ]
        print(
            f"📋 Field validation: {len(expected_fields) - len(missing_fields)}/{len(expected_fields)} fields present", flush=True
        )

        # If there are missing fields, make follow-up requests
        if missing_fields:
            print(f"⚠️ Missing fields detected: {missing_fields}", flush=True)
            print("🔄 Attempting follow-up request for missing fields...", flush=True)

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
            missing_properties = {field: nelda_variable_schema for field in missing_fields}
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
                    f"✓ Successfully retrieved missing fields: {list(followup_parsed.keys())}", flush=True
                )

            except Exception as e:
                print(f"⚠️ Follow-up request failed: {e}", flush=True)
                # Continue with partial response

        # Final validation - log any still missing fields
        still_missing = [
            field for field in expected_fields if field not in parsed_response
        ]
        if still_missing:
            print(f"⚠️ Still missing fields after follow-up: {still_missing}", flush=True)
        else:
            print("✅ All NELDA fields successfully retrieved!", flush=True)

        print("🏗️ Preparing data for MongoDB storage...", flush=True)
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
        print("✓ Document prepared for MongoDB", flush=True)

        # Store in MongoDB
        print("💾 Storing in MongoDB...", flush=True)
        try:
            mongodb_result = store_in_mongodb(mongodb_document)
            print(f"✅ Successfully stored analysis in MongoDB: {mongodb_result}", flush=True)
            print("=== BACKGROUND NELDA PROCESSING COMPLETED SUCCESSFULLY ===", flush=True)

        except Exception as e:
            print(f"❌ Failed to store in MongoDB: {e}", flush=True)
            print("=== BACKGROUND NELDA PROCESSING FAILED ===", flush=True)

    except Exception as e:
        print(f"❌ UNHANDLED ERROR in background processing: {e}", flush=True)
        print("=== BACKGROUND NELDA PROCESSING FAILED ===", flush=True)


def store_in_mongodb(data):
    """Store election analysis data in MongoDB using pymongo."""
    username = os.environ.get("MONGODB_USERNAME")
    password = os.environ.get("MONGODB_PASSWORD")

    if not username or not password:
        raise ValueError(
            "MONGODB_USERNAME and MONGODB_PASSWORD must be set in environment variables"
        )

    # MongoDB connection string for Atlas
    connection_string = f"mongodb+srv://{username}:{password}@socialchoice.bsut1.mongodb.net/?retryWrites=true&w=majority"

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
        print("=== NELDA API REQUEST START (ASYNC MODE) ===", flush=True)

        # Get JSON data from request body
        data = request.get_json()
        print(f"Received request data: {data}", flush=True)

        # Extract required parameters for validation
        election_id = data.get("electionId")
        country_name = data.get("countryName")
        election_types = data.get("types")
        year = data.get("year")
        mmdd = data.get("mmdd")
        pre = data.get("pre")

        print(f"Validating parameters:", flush=True)
        print(f"  - electionId: {election_id}", flush=True)
        print(f"  - countryName: {country_name}", flush=True)
        print(f"  - types: {election_types}", flush=True)
        print(f"  - year: {year}", flush=True)
        print(f"  - mmdd: {mmdd}", flush=True)
        print(f"  - pre: {pre}", flush=True)

        # Validate required parameters
        if not all(
            [election_id, country_name, election_types, year, mmdd, pre is not None]
        ):
            print("ERROR: Missing required parameters", flush=True)
            return jsonify({"error": "Missing required parameters"}), 400

        print("✓ All required parameters present", flush=True)

        # Start background processing
        print("🚀 Starting background processing thread...", flush=True)
        processing_thread = threading.Thread(
            target=process_nelda_analysis_background, 
            args=(data,),
            daemon=True  # Thread will die when main program exits
        )
        processing_thread.start()
        
        print("✅ Background processing started successfully", flush=True)
        print("=== RETURNING IMMEDIATE RESPONSE TO CLIENT ===", flush=True)

        # Return immediate response to client
        return jsonify({
            "success": True,
            "message": "Election analysis started in background",
            "status": "processing",
            "electionId": election_id,
            "note": "Processing will continue even if request times out. Check server logs for completion status."
        }), 202  # 202 Accepted - request accepted for processing

    except Exception as e:
        print(f"❌ UNHANDLED ERROR in request handler: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # Enable debug mode and unbuffered output
    app.run(host="0.0.0.0", port=5050, debug=True)

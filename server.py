from flask import Flask, request, jsonify
from google import genai
from google.genai import types
import os
import base64

# Create an instance of the Flask class
app = Flask(__name__)

# Configure Gemini API
client = genai.Client(api_key=os.environ.get('GEMINI_API_KEY'))

@app.route('/runNelda', methods=['POST'])
def run_my_script():
    try:
        # Get JSON data from request body
        data = request.get_json()
        
        # Extract required parameters
        election_id = data.get('electionId')
        country_name = data.get('countryName')
        types = data.get('types')
        year = data.get('year')
        mmdd = data.get('mmdd')
        
        # Validate required parameters
        if not all([election_id, country_name, types, year, mmdd]):
            return jsonify({'error': 'Missing required parameters'}), 400
        
        # Compose prompt using the parameters
        prompt = f"""
        Analyze election data for the following parameters:
        Election ID: {election_id}
        Country: {country_name}
        Types: {types}
        Year: {year}
        Date (MMDD): {mmdd}
        
        Please provide insights about this election data.
        """
        
        # Read the NELDA codebook PDF
        with open('/Users/samueltaplin/research/llmneldacoding/NELDA_Codebook_V5.pdf', 'rb') as pdf_file:
            pdf_data = pdf_file.read()
        
        # Configure generation config
        generation_config = types.GenerateContentConfig(
            system_instruction="You are an expert in election monitoring and the NELDA dataset coding system.",
            thinking_config = types.ThinkingConfig(
            thinking_budget=-1,
            ),
            response_mime_type="text/plain",
        )
        
        # Send prompt to Gemini API
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            tools=[types.Tool(google_search=types.GoogleSearch())],
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(
                            mime_type="application/pdf",
                            data=pdf_data,
                        ),
                        types.Part.from_text(text=f"""I've uploaded the codebook for the NELDA dataset.

Your task: Based on an election, and the coding rules in the codebook, code the NELDA1 to NELDA58 variables for the election I give you. Explain your choice of coding and clearly articulate your coding of 'Yes', 'No', 'Unclear' or 'N/A'.

Use live web search to gather current information about this election to inform your coding decisions.

Remember to double check your answer to make sure that your coding matches the explanation you gave for the choice.

The election details:
- Election ID: {election_id}
- Country: {country_name}
- Election Types: {types}
- Year: {year}
- Date (MM/DD): {mmdd}

Please analyze this specific election and provide NELDA coding for all relevant variables."""),
                    ],
                )
            ],
            config=generation_config
        )
        
        return jsonify({
            'success': True,
            'response': response.text,
            'parameters': {
                'electionId': election_id,
                'countryName': country_name,
                'types': types,
                'year': year,
                'mmdd': mmdd
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
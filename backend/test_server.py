import cv2
import numpy as np
import urllib.request
import urllib.parse
import json
import time
import os
import mimetypes

def create_test_image(text="VR12345"):
    # Create a white image
    img = np.ones((300, 600, 3), dtype=np.uint8) * 255
    
    # Add text
    font = cv2.FONT_HERSHEY_SIMPLEX
    # (image, text, org, font, fontScale, color, thickness, lineType)
    cv2.putText(img, text, (50, 150), font, 3, (0, 0, 0), 5, cv2.LINE_AA)
    
    # Save it
    filename = "test_vr.jpg"
    cv2.imwrite(filename, img)
    return filename

def test_api():
    print("Generating test image...")
    filename = create_test_image()
    
    url = "http://127.0.0.1:8000/api/process"
    print(f"Sending {filename} to {url}...")
    
    boundary = '----WebKitFormBoundary7MA4YWxkTrZu0gW'
    
    with open(filename, "rb") as f:
        file_content = f.read()
        
    # Construct multipart form data manually
    data = []
    data.append(f'--{boundary}')
    data.append(f'Content-Disposition: form-data; name="files"; filename="{filename}"')
    data.append('Content-Type: image/jpeg')
    data.append('')
    data.append(file_content.decode('latin1')) 
    data.append(f'--{boundary}--')
    data.append('')
    
    body = '\r\n'.join(data).encode('latin1')
    
    req = urllib.request.Request(url, data=body)
    req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
    
    try:
        with urllib.request.urlopen(req) as response:
            status_code = response.getcode()
            response_body = response.read().decode('utf-8')
            
            if status_code == 200:
                data = json.loads(response_body)
                print("\nResponse Received:")
                print(json.dumps(data, indent=2))
                
                # Check correctness
                processed = data.get("processed", [])
                if processed and processed[0]["new_name"].startswith("VR12345"):
                    print("\n✅ SUCCESS: API correctly identified VR12345")
                else:
                    print("\n❌ FAILURE: API did not identify VR12345")
            else:
                print(f"\n❌ Error: Status Code {status_code}")
                print(response_body)
                
    except urllib.error.HTTPError as e:
         print(f"\n❌ HTTP Error: {e.code}")
         print(e.read().decode())
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        
    finally:
        if os.path.exists(filename):
            pass # Keep it for inspection if needed, or os.remove(filename)

if __name__ == "__main__":
    print("Waiting for server...")
    time.sleep(2)
    test_api()

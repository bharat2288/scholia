"""Check if sessions router imports correctly."""
import sys
sys.path.insert(0, ".")

try:
    from routers.sessions import router, RLMChatRequest, RLMChatResponse

    # Check RLM endpoint exists
    routes = [r.path for r in router.routes]
    print("Routes:", routes)

    if "/{session_id}/rlm" in routes:
        print("SUCCESS: RLM endpoint found")
    else:
        print("ERROR: RLM endpoint NOT found in routes")

except Exception as e:
    print(f"Import error: {e}")
    import traceback
    traceback.print_exc()

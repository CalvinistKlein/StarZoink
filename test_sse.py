import sys, os
sys.path.insert(0, "/home/hugo/workspace/DungeonOfTheStars")
os.chdir("/home/hugo/workspace/DungeonOfTheStars")

import dungeonofthestars as appmod

class FakeEngine:
    def execute_turn(self, cmd, stream_callback=None):
        for w in ["The ", "crew ", "stands ", "ready."]:
            if stream_callback:
                stream_callback(w)
        return "The crew stands ready. **STATUS** nominal."

appmod.engine = FakeEngine()
client = appmod.app.test_client()

r = client.post('/api/command', json={'command': 'test'})
data = r.get_data(as_text=True)
print("status_code:", r.status_code)
print("contains 'event: done':", 'event: done' in data)
print("contains html payload:", '"html"' in data)
print("contains token frames:", data.count('"token"'))
print("---- raw SSE (first 400 chars) ----")
print(data[:400])

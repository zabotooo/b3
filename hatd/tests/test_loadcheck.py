from b3hatd.loadcheck import loadcheck


async def test_loadcheck_against_local_server(client):
    base = str(client.server.make_url("")).rstrip("/")
    rates = await loadcheck(base, "1234", clients=2, seconds=0.5)
    assert len(rates) == 2
    assert all(rate > 10 for rate in rates)  # test config: telemetry every 0.02 s

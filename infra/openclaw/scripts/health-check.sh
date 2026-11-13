#!/bin/bash
# OpenClaw Health Check Script - Verify gateway is running and responding

set -e

GATEWAY_URL="http://127.0.0.1:18789"
TIMEOUT=10
RETRIES=3

echo "Checking OpenClaw gateway health..."
echo "URL: ${GATEWAY_URL}"
echo ""

# Try basic connectivity
for i in $(seq 1 ${RETRIES}); do
    echo -n "[${i}/${RETRIES}] Testing connection... "
    
    if timeout ${TIMEOUT} curl -s "${GATEWAY_URL}/health" > /dev/null 2>&1; then
        echo "✓ HEALTHY"
        echo ""
        echo "Gateway is operational."
        
        # Show container status
        docker compose ps openclaw-gateway 2>/dev/null || echo "Note: Docker Compose status unavailable"
        exit 0
    else
        echo "✗ No response"
        if [ ${i} -lt ${RETRIES} ]; then
            sleep 2
        fi
    fi
done

echo ""
echo "WARNING: Gateway health check failed after ${RETRIES} attempts."
echo ""
echo "Troubleshooting:"
echo "  1. Check container logs: docker compose logs openclaw-gateway"
echo "  2. Verify container is running: docker ps | grep openclaw"
echo "  3. Check port is bound: netstat -tuln | grep 18789"
echo "  4. Verify configuration: cat .env.local | grep -i token"
echo ""
exit 1

#!/bin/bash

# Create a dummy interface
create_link(){
        ip link add dummy0 type dummy
        ip addr add 10.1.0.1/16 dev dummy0
        ip link set dummy0 up
}

delete_link(){
        ip link delete dummy0
        iptables -t nat -D PREROUTING -d 10.1.0.0/16 -p tcp --dport 80 -j DNAT --to-destination 10.1.0.1:80
        sysctl -w net.ipv4.ip_forward=0
}

# setup server
start_server(){
        python3 - <<'EOF' &
from http.server import BaseHTTPRequestHandler, HTTPServer

class IPHandler(BaseHTTPRequestHandler):
        def do_GET(self):
                client_ip = self.client_address[0]
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write((client_ip+'\n').encode("utf-8"))
if __name__ == '__main__':
        server = HTTPServer(('10.1.0.1', 80), IPHandler)
        server.serve_forever()
EOF
        SERVER_PID=$!
        echo "IP ehco HTTP server started on 127.0.0.1:80 (PID $SERVER_PID)"
}

# setup routing
setup_redir(){
        iptables -t nat -A PREROUTING -d 10.1.0.0/16 -p tcp --dport 80 -j DNAT --to-destination 10.1.0.1:80
        sysctl -w net.ipv4.ip_forward=1
}

cleanup(){
        echo "Cleaning up..."
        kill "$SERVER_PID" 2>/dev/null
        delete_link
        exit
}

# setup signal handler
trap cleanup SIGINT SIGTERM

create_link
setup_redir
start_server

# wait for the server to exit
wait $SERVER_PID

cleanup

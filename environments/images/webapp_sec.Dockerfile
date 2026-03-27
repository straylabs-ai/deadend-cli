FROM parrotsec/core:6

RUN apt update -y 
RUN apt install \
    nmap nbtscan
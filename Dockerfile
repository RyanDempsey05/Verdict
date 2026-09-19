FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl fontconfig \
    && mkdir -p /usr/share/fonts/truetype/verdict \
    && curl -sL -o /usr/share/fonts/truetype/verdict/Inter-Regular.ttf \
       https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf \
    && curl -sL -o /usr/share/fonts/truetype/verdict/Cinzel.ttf \
       https://github.com/google/fonts/raw/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf \
    && fc-cache -f \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /code
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

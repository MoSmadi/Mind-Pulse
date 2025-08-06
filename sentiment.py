# sentiment.py
from nltk.sentiment import SentimentIntensityAnalyzer
import nltk

nltk.download('vader_lexicon', quiet=True)
sia = SentimentIntensityAnalyzer()

def analyze_sentiment(text):
    score = sia.polarity_scores(text)['compound']
    label = (
        "positive" if score > 0.3 else
        "negative" if score < -0.3 else
        "neutral"
    )
    return {"label": label, "score": score}

import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# Download required lexicon (only runs once)
nltk.download('vader_lexicon', quiet=True)

# Initialize the VADER sentiment analyzer
sia = SentimentIntensityAnalyzer()

def analyze_sentiment(text):
    """
    Analyze the sentiment of a given text using VADER.

    Returns:
        {
            "label": "positive" | "neutral" | "negative",
            "score": float
        }
    """
    score = sia.polarity_scores(text)['compound']
    
    # Classify based on compound score
    if score > 0.3:
        label = "positive"
    elif score < -0.3:
        label = "negative"
    else:
        label = "neutral"

    return {
        "label": label,
        "score": score
    }

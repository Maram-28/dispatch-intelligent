import pandas as pd
import random
from tqdm import tqdm
from tabulate import tabulate
from src.preprocessing.prepare_data import load_and_clean, compute_accuracy
from src.agents.ticket_crew import TicketInput, classify_ticket

def run_benchmark(n_samples=10):
    print(f"🚀 Starting Benchmark with {n_samples} random tickets...")
    
    # 1. Load Data
    input_file = "data/raw/incident-10000.xlsx"
    df = load_and_clean(input_file)
    
    # 2. Sample random tickets
    sample_df = df.sample(n_samples, random_state=random.randint(1, 1000))
    
    predictions = []
    ground_truths = []
    
    # 3. Process each ticket
    for _, row in tqdm(sample_df.iterrows(), total=n_samples, desc="Classifying"):
        ticket = TicketInput(
            numero=str(row["numero"]),
            breve_description=str(row["breve_description"]),
            description=str(row["description"]),
            entreprise=str(row.get("entreprise", ""))
        )
        
        try:
            # Run the AI Agent
            prediction = classify_ticket(ticket)
            
            # Prepare for comparison
            predictions.append(prediction.dict())
            ground_truths.append({
                "ground_truth": {
                    "categorie": row["categorie"],
                    "sous_categorie": row["sous_categorie"],
                    "service": row["service"],
                    "impact": row["impact"],
                    "urgence": row["urgence"]
                }
            })
        except Exception as e:
            print(f"\n❌ Error on ticket {row['numero']}: {e}")
            continue
            
        # Add a delay to avoid Rate Limits (Groq TPM/RPM)
        import time
        time.sleep(10)

    # 4. Compute Metrics
    results = compute_accuracy(predictions, ground_truths)
    
    # 5. Display Summary
    print("\n" + "="*50)
    print("📊 BENCHMARK RESULTS")
    print("="*50)
    
    table_data = []
    for field, metrics in results.items():
        table_data.append([
            field.upper(), 
            f"{metrics['accuracy']*100:.1f}%", 
            f"{metrics['correct']}/{metrics['total']}"
        ])
    
    print(tabulate(table_data, headers=["Field", "Accuracy", "Correct/Total"], tablefmt="grid"))
    
    # 6. Detailed comparison for first 3 samples
    print("\n🔍 DETAILED COMPARISON (Top 3):")
    for i in range(min(3, len(predictions))):
        p = predictions[i]
        gt = ground_truths[i]["ground_truth"]
        print(f"\nTicket: {p['numero']}")
        details = [
            ["Field", "Prediction", "Ground Truth", "Status"],
            ["Category", p['categorie'], gt['categorie'], "✅" if p['categorie'] == gt['categorie'] else "❌"],
            ["Service", p['service'], gt['service'], "✅" if p['service'] == gt['service'] else "❌"],
            ["Impact", p['impact'], gt['impact'], "✅" if p['impact'] == gt['impact'] else "❌"],
        ]
        print(tabulate(details, headers="firstrow", tablefmt="simple"))

if __name__ == "__main__":
    # You can change the number of samples here
    run_backend_status = "Make sure your LLM API keys are set in .env"
    run_benchmark(n_samples=5)

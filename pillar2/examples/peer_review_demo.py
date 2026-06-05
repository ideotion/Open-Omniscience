"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism

Copyright (C) 2026 Ideotion

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.

For inquiries, contact: open-omniscience@ideotion.com
"""
#!/usr/bin/env python3
"""
Peer-Review Simulation and Reproducibility Scoring Demo
Open-Omniscience - Pillar 2: Scientific Rigor - Phases 2.2 and 2.3

This script demonstrates the peer-review simulation and reproducibility scoring features.
"""

import sys
sys.path.insert(0, '/workspace')

from pillar2.src.analysis.peer_review import (
    PeerReviewSimulator,
    PeerReviewSession,
    ReviewResult,
    BlindReview,
    ReviewStatus,
    ReviewDecision
)
from pillar2.src.analysis.consensus import ConsensusCalculator, ConsensusResult
from pillar2.src.analysis.reproducibility import (
    ReproducibilityCalculator,
    ReproducibilityScore,
    DataLineageTracker,
    DataLineage,
    DataSourceType
)


def demo_peer_review():
    """Demonstrate peer-review simulation."""
    print("=" * 80)
    print("PHASE 2.2: PEER-REVIEW SIMULATION DEMO")
    print("=" * 80)
    print()
    
    # Create a sample research abstract
    research_content = """
    Title: The Impact of Statistical Rigor on Research Reproducibility
    
    Abstract:
    This study investigates the correlation between statistical rigor and research 
    reproducibility across 500 published papers. We found that papers with comprehensive
    statistical validation had a 40% higher reproducibility score than those without.
    
    Methods:
    - Collected data from 500 papers across multiple disciplines
    - Applied t-tests, ANOVA, and regression analysis
    - Calculated reproducibility scores using our custom framework
    
    Results:
    - Strong positive correlation (r=0.75, p<0.001)
    - Statistical rigor explains 56% of variance in reproducibility
    
    Conclusion:
    Statistical rigor is a key predictor of research reproducibility.
    """
    
    print("Sample Research Content:")
    print("-" * 80)
    print(research_content)
    print()
    
    # Initialize peer-review simulator
    print("Initializing Peer-Review Simulator...")
    simulator = PeerReviewSimulator(
        ollama_base_url="http://localhost:11434",
        default_models=["llama3.2:3b", "mistral:7b"],
        timeout=120
    )
    print(f"✓ Simulator initialized with {len(simulator.default_models)} default models")
    print()
    
    # Create a review session
    print("Creating review session...")
    session = simulator.create_session(
        content=research_content,
        models=["model1", "model2", "model3"]  # Using placeholder model names
    )
    print(f"✓ Session created: {session.id}")
    print(f"  Content hash: {session.content_hash[:16]}...")
    print()
    
    # Add mock reviews (since we don't have Ollama running)
    print("Adding mock reviews (simulating LLM responses)...")
    session.add_review(ReviewResult(
        model_name="model1",
        model_id="review_001",
        review_text="This is a well-structured study with clear methodology. The statistical analysis is comprehensive. Score: 90",
        score=90.0,
        decision=ReviewDecision.ACCEPT,
        confidence=0.95,
        review_time=5.5
    ))
    
    session.add_review(ReviewResult(
        model_name="model2",
        model_id="review_002",
        review_text="Good study overall. The sample size is adequate. Some minor improvements needed in documentation. Score: 85",
        score=85.0,
        decision=ReviewDecision.MINOR_REVISIONS,
        confidence=0.90,
        review_time=6.2
    ))
    
    session.add_review(ReviewResult(
        model_name="model3",
        model_id="review_003",
        review_text="Excellent research with rigorous statistical methods. Highly reproducible. Score: 95",
        score=95.0,
        decision=ReviewDecision.ACCEPT,
        confidence=0.98,
        review_time=4.8
    ))
    
    session.mark_completed()
    print(f"✓ Added {len(session.reviews)} reviews")
    print()
    
    # Display session summary
    print("Session Summary:")
    print("-" * 80)
    print(f"Average Score: {session.get_average_score():.2f}/100")
    print(f"Average Confidence: {session.get_average_confidence():.2%}")
    print(f"Status: {session.status.value}")
    print()
    
    # Create a blind review
    print("Creating blind review (metadata hidden)...")
    blind_review = simulator.create_blind_review(
        content=research_content,
        model="model1"
    )
    print(f"✓ Blind review created: {blind_review.review_id}")
    print(f"  Score: {blind_review.score}/100")
    print(f"  Decision: {blind_review.decision.value}")
    print()


def demo_consensus():
    """Demonstrate consensus scoring."""
    print("=" * 80)
    print("PHASE 2.2: CONSENSUS SCORING DEMO")
    print("=" * 80)
    print()
    
    # Create a session with reviews
    session = PeerReviewSession(
        id="consensus_test",
        content="Test content",
        content_hash="abc123"
    )
    
    # Add reviews with varying decisions
    session.add_review(ReviewResult(
        model_name="model1", model_id="r1", review_text="Accept",
        score=90.0, decision=ReviewDecision.ACCEPT, confidence=0.95, review_time=5.0
    ))
    session.add_review(ReviewResult(
        model_name="model2", model_id="r2", review_text="Accept",
        score=88.0, decision=ReviewDecision.ACCEPT, confidence=0.90, review_time=6.0
    ))
    session.add_review(ReviewResult(
        model_name="model3", model_id="r3", review_text="Minor revisions",
        score=75.0, decision=ReviewDecision.MINOR_REVISIONS, confidence=0.85, review_time=7.0
    ))
    
    # Calculate consensus
    calculator = ConsensusCalculator(agreement_threshold=0.8)
    result = calculator.calculate_consensus(session)
    
    print("Consensus Calculation Results:")
    print("-" * 80)
    print(f"Agreement Score: {result.agreement_score:.2%}")
    print(f"Average Score: {result.average_score:.2f}/100")
    print(f"Average Confidence: {result.average_confidence:.2%}")
    print(f"Consensus Decision: {result.consensus_decision.value}")
    print(f"Score Standard Deviation: {result.score_std_dev:.2f}")
    print()
    
    print("Decision Distribution:")
    for decision, count in result.decision_distribution.items():
        print(f"  {decision}: {count} review(s)")
    print()
    
    print(f"Has Consensus: {calculator.has_consensus(session)}")
    print()
    
    # Get summary
    summary = calculator.get_consensus_summary(session)
    print("Consensus Summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    print()
    
    # Calculate pairwise agreement
    pairwise_agreement = calculator.calculate_pairwise_agreement(session.reviews)
    print(f"Pairwise Agreement: {pairwise_agreement:.2%}")
    print()


def demo_reproducibility():
    """Demonstrate reproducibility scoring."""
    print("=" * 80)
    print("PHASE 2.3: REPRODUCIBILITY SCORING DEMO")
    print("=" * 80)
    print()
    
    # Initialize calculator
    calculator = ReproducibilityCalculator()
    
    # Scenario 1: Perfect reproducibility
    print("Scenario 1: Perfect Reproducibility")
    print("-" * 80)
    score1 = calculator.calculate_score(
        data_available=True,
        methods_described=True,
        code_available=True,
        documentation_complete=True
    )
    print(f"Overall Score: {score1.overall_score:.1f}/100")
    print(f"Grade: {score1.grade}")
    print(f"Issues: {score1.issues if score1.issues else 'None'}")
    print()
    
    # Scenario 2: Partial reproducibility
    print("Scenario 2: Partial Reproducibility")
    print("-" * 80)
    score2 = calculator.calculate_score(
        data_available=True,
        methods_described=True,
        code_available=False,
        documentation_complete=True
    )
    print(f"Overall Score: {score2.overall_score:.1f}/100")
    print(f"Grade: {score2.grade}")
    print(f"Issues: {score2.issues}")
    print()
    
    # Scenario 3: Poor reproducibility
    print("Scenario 3: Poor Reproducibility")
    print("-" * 80)
    score3 = calculator.calculate_score(
        data_available=False,
        methods_described=False,
        code_available=False,
        documentation_complete=False
    )
    print(f"Overall Score: {score3.overall_score:.1f}/100")
    print(f"Grade: {score3.grade}")
    print(f"Issues: {score3.issues}")
    print()
    
    # Generate a report
    print("Sample Reproducibility Report:")
    print("-" * 80)
    report = calculator.generate_report(score2)
    print(report)
    print()


def demo_data_lineage():
    """Demonstrate data lineage tracking."""
    print("=" * 80)
    print("PHASE 2.3: DATA LINEAGE TRACKING DEMO")
    print("=" * 80)
    print()
    
    # Initialize tracker
    tracker = DataLineageTracker()
    
    # Add raw data source
    print("Adding raw data source...")
    raw_data = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    source_lineage = tracker.add_source(
        source="raw_data.csv",
        data=raw_data,
        source_type=DataSourceType.RAW,
        processing_steps=["loaded from CSV"],
        metadata={"format": "CSV", "rows": 10}
    )
    print(f"✓ Source added: {source_lineage.source}")
    print(f"  Hash: {source_lineage.data_hash[:16]}...")
    print()
    
    # Add processing step
    print("Adding processing step: cleaning...")
    cleaned_data = [x for x in raw_data if x > 2]  # Remove values <= 2
    cleaned_lineage = tracker.add_processing_step(
        input_hash=source_lineage.data_hash,
        output_data=cleaned_data,
        step_description="removed outliers",
        output_source="cleaned_data.csv"
    )
    print(f"✓ Processing step added: {cleaned_lineage.source}")
    print(f"  Steps: {cleaned_lineage.processing_steps}")
    print(f"  Dependencies: {cleaned_lineage.dependencies}")
    print()
    
    # Add another processing step
    print("Adding processing step: normalization...")
    normalized_data = [x / max(cleaned_data) for x in cleaned_data]
    normalized_lineage = tracker.add_processing_step(
        input_hash=cleaned_lineage.data_hash,
        output_data=normalized_data,
        step_description="normalized to [0,1]",
        output_source="normalized_data.csv"
    )
    print(f"✓ Processing step added: {normalized_lineage.source}")
    print(f"  Steps: {normalized_lineage.processing_steps}")
    print()
    
    # Get full lineage
    print("Full Data Lineage Chain:")
    print("-" * 80)
    full_lineage = tracker.get_full_lineage(normalized_lineage.data_hash)
    for i, step in enumerate(full_lineage, 1):
        print(f"{i}. {step.source} ({step.source_type.value})")
        print(f"   Hash: {step.data_hash[:16]}...")
        print(f"   Steps: {step.processing_steps}")
        if step.dependencies:
            print(f"   Depends on: {step.dependencies[0][:16]}...")
        print()
    
    # Export lineage
    print("Exporting lineage...")
    exported = tracker.export_lineage()
    print(f"✓ Exported {len(exported)} lineage records")
    print()


def main():
    """Run all demos."""
    print()
    print("=" * 80)
    print("OPEN-OMNISCIENCE - PILLAR 2: SCIENTIFIC RIGOR")
    print("Phases 2.2 and 2.3 Demo")
    print("=" * 80)
    print()
    
    try:
        demo_peer_review()
        demo_consensus()
        demo_reproducibility()
        demo_data_lineage()
        
        print("=" * 80)
        print("ALL DEMOS COMPLETED SUCCESSFULLY!")
        print("=" * 80)
        print()
        print("Note: To run with actual Ollama models, start Ollama and run:")
        print("  ollama pull llama3.2:3b")
        print("  ollama pull mistral:7b")
        print()
        
    except Exception as e:
        print(f"Error during demo: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

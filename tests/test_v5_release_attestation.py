from src.v5.release_attestation import release_attestation

def test_release_attestation_binds_current_candidate():
    row=release_attestation(); assert row["contract"]=="V5_RELEASE_ATTESTATION_V1"; assert row["v5_version"]=="5.0.0-beta.4"; assert row["production_baseline_version"]=="v3.20.0"; assert row["production_main_sha"]=="15e75599045f901958753c2bcb275fceacc94d7c"; assert str(row["runtime_release_fingerprint"]).startswith("sha256:"); assert str(row["attestation"]).startswith("sha256:"); assert row["promotion_authority"] is False

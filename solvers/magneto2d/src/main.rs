fn main() -> Result<(), Box<dyn std::error::Error>> {
    magneto2d::run_cli(std::env::args().skip(1))
}

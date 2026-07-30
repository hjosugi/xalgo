{
  description = "Reproducible development environment for xalgo";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { nixpkgs, ... }:
    let
      supportedSystems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-darwin"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs supportedSystems;
    in
    {
      devShells = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          python = pkgs.python312.withPackages (pythonPackages: [
            pythonPackages.requests
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.actionlint
              pkgs.go-task
              pkgs.nodejs_22
              pkgs.nixfmt
              pkgs.ruff
              python
            ];
          };
        }
      );

      formatter = forAllSystems (system: nixpkgs.legacyPackages.${system}.nixfmt);
    };
}

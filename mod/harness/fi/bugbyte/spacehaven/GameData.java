package fi.bugbyte.spacehaven;

public class GameData {
    public static class SaveGame {
        private final String folder;
        public SaveGame(String folder) { this.folder = folder; }
        public boolean isSlaveWorldActive(boolean autosave, int slot) {
            return false;
        }
        public String getFolderName() { return folder; }
    }
}

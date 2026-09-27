package se.urbanEV.pv;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.matsim.api.core.v01.Id;
import se.urbanEV.fleet.ElectricVehicle;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PvVehicleCsvLoaderTest {
    @TempDir
    Path tempDir;

    @Test
    void parsesHeaderCommentsAndQuotedFirstColumn() throws IOException {
        Path csv = tempDir.resolve("cohort.csv");
        Files.writeString(csv, "vehicleId,group\n# comment\n\"ev,one\",A\nev-two,B\n");

        Set<Id<ElectricVehicle>> ids = PvVehicleCsvLoader.loadCsv(csv.toString());
        assertTrue(ids.contains(Id.create("ev,one", ElectricVehicle.class)));
        assertTrue(ids.contains(Id.create("ev-two", ElectricVehicle.class)));
    }

    @Test
    void rejectsDuplicateIds() throws IOException {
        Path csv = tempDir.resolve("duplicates.csv");
        Files.writeString(csv, "id\nev-1\nev-1\n");

        assertThrows(IllegalArgumentException.class,
                () -> PvVehicleCsvLoader.loadCsv(csv.toString()));
    }

    @Test
    void rejectsMissingExplicitFile() {
        assertThrows(IllegalArgumentException.class,
                () -> PvVehicleCsvLoader.loadCsv(tempDir.resolve("missing.csv").toString()));
    }
}
